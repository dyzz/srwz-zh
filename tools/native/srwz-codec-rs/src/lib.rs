//! Clean-room SRWZ compressor.
//!
//! The stream grammar is implemented from the repository's independently
//! documented decoder contract. No upstream source is included here.

use std::cmp::min;
use std::fmt;

const NONE: u32 = u32::MAX;
const MAX_MATCH_LENGTH: usize = 0x00ff_ffff;
const MEDIUM_CHAIN_LIMIT: usize = 4096;
const MIN_HASH_HEADS: usize = 1 << 16;
const MAX_HASH_HEADS: usize = 1 << 18;

#[derive(Clone, Copy, Debug)]
pub struct EncodeOptions {
    pub window_size: usize,
    pub min_match_length: usize,
    pub max_match_chain: usize,
    pub prefix_size: usize,
    /// Select one lazy-match bias for a faster single pass. `None` exhaustively
    /// tries the clean-room reference range 0..=8 and keeps the smallest stream.
    pub lazy_bias: Option<u8>,
}

impl EncodeOptions {
    pub fn validate(&self, size: usize) -> Result<(), EncodeError> {
        if self.window_size == 0 {
            return Err(EncodeError::new("window size must be positive"));
        }
        if self.min_match_length < 2 {
            return Err(EncodeError::new(
                "minimum match length must be at least two",
            ));
        }
        if self.max_match_chain == 0 {
            return Err(EncodeError::new("maximum match chain must be positive"));
        }
        if self.prefix_size > size {
            return Err(EncodeError::new("prefix size is outside the decoded input"));
        }
        if self.lazy_bias.is_some_and(|bias| bias > 8) {
            return Err(EncodeError::new("lazy bias must be between zero and eight"));
        }
        if size > u32::MAX as usize {
            return Err(EncodeError::new(
                "decoded input exceeds the 32-bit compressor limit",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct EncodeError {
    message: String,
}

impl EncodeError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for EncodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for EncodeError {}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct Match {
    distance: u32,
    length: u32,
}

struct MatchIndex {
    previous2: Vec<u32>,
    previous4: Vec<u32>,
    previous16: Vec<u32>,
    heads2: Vec<u32>,
    heads4: Vec<u32>,
    heads16: Vec<u32>,
    hash_mask: usize,
}

fn coded_integer_size(mut value: usize) -> usize {
    let mut size = 1;
    while value >= 0x80 {
        value >>= 7;
        size += 1;
    }
    size
}

pub fn encode_coded_integer(mut value: usize) -> Vec<u8> {
    let mut groups = [0u8; 10];
    let mut start = groups.len() - 1;
    groups[start] = (value & 0x7f) as u8;
    value >>= 7;
    while value != 0 {
        start -= 1;
        groups[start] = (value & 0x7f) as u8;
        value >>= 7;
    }
    let mut encoded = Vec::with_capacity(groups.len() - start);
    for (index, group) in groups[start..].iter().enumerate() {
        let terminal = index + 1 == groups.len() - start;
        encoded.push((group << 1) | u8::from(terminal));
    }
    encoded
}

fn compact_match_size(distance: usize, length: usize) -> usize {
    let distance_value = distance - 1;
    let distance_extension_size = if distance_value <= 7 {
        0
    } else {
        let groups = coded_integer_size(distance_value);
        let top_group = distance_value >> (7 * (groups - 1));
        if groups > 1 && top_group < 8 {
            groups - 1
        } else {
            groups
        }
    };
    let length_value = length - 1;
    let length_extension_size = if length_value <= 0x0f {
        0
    } else {
        coded_integer_size(length_value)
    };
    1 + distance_extension_size + length_extension_size
}

fn maximum_gain_upper_bound(maximum_length: usize) -> i32 {
    if maximum_length < 2 {
        return 0;
    }
    let short_gain = min(maximum_length, 16) - 1;
    if maximum_length <= 16 {
        return short_gain as i32;
    }
    let long_gain = maximum_length - 1 - coded_integer_size(maximum_length - 1);
    short_gain.max(long_gain) as i32
}

fn hash4(data: &[u8], position: usize) -> usize {
    let value = u32::from_le_bytes(
        data[position..position + 4]
            .try_into()
            .expect("four-byte key bounds checked"),
    );
    value.wrapping_mul(0x9e37_79b1) as usize
}

fn hash16(data: &[u8], position: usize) -> usize {
    let first = u64::from_le_bytes(
        data[position..position + 8]
            .try_into()
            .expect("first eight-byte key bounds checked"),
    );
    let second = u64::from_le_bytes(
        data[position + 8..position + 16]
            .try_into()
            .expect("second eight-byte key bounds checked"),
    );
    let mut hash = first ^ second.rotate_left(23);
    hash ^= hash >> 30;
    hash = hash.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    hash ^= hash >> 27;
    hash = hash.wrapping_mul(0x94d0_49bb_1331_11eb);
    (hash ^ (hash >> 31)) as usize
}

impl MatchIndex {
    fn new(size: usize) -> Self {
        let requested_heads = size
            .div_ceil(2)
            .next_power_of_two()
            .clamp(MIN_HASH_HEADS, MAX_HASH_HEADS);
        Self {
            previous2: vec![NONE; size],
            previous4: vec![NONE; size],
            previous16: vec![NONE; size],
            heads2: vec![NONE; 1 << 16],
            heads4: vec![NONE; requested_heads],
            heads16: vec![NONE; requested_heads],
            hash_mask: requested_heads - 1,
        }
    }

    fn add_position(&mut self, data: &[u8], position: usize) {
        if position + 2 <= data.len() {
            let key = ((data[position] as usize) << 8) | data[position + 1] as usize;
            self.previous2[position] = self.heads2[key];
            self.heads2[key] = position as u32;
        }
        if position + 4 <= data.len() {
            let bucket = hash4(data, position) & self.hash_mask;
            self.previous4[position] = self.heads4[bucket];
            self.heads4[bucket] = position as u32;
        }
        if position + 16 <= data.len() {
            let bucket = hash16(data, position) & self.hash_mask;
            self.previous16[position] = self.heads16[bucket];
            self.heads16[bucket] = position as u32;
        }
    }

    fn head2(&self, data: &[u8], position: usize) -> u32 {
        if position + 2 > data.len() {
            return NONE;
        }
        let key = ((data[position] as usize) << 8) | data[position + 1] as usize;
        self.heads2[key]
    }

    fn head4(&self, data: &[u8], position: usize) -> u32 {
        if position + 4 > data.len() {
            return NONE;
        }
        self.heads4[hash4(data, position) & self.hash_mask]
    }

    fn head16(&self, data: &[u8], position: usize) -> u32 {
        if position + 16 > data.len() {
            return NONE;
        }
        self.heads16[hash16(data, position) & self.hash_mask]
    }
}

fn match_gain(found: Match) -> i32 {
    if found.distance == 0 || found.length < 2 {
        0
    } else {
        found.length as i32
            - compact_match_size(found.distance as usize, found.length as usize) as i32
    }
}

fn match_length(
    data: &[u8],
    position: usize,
    candidate: usize,
    known_length: usize,
    maximum_length: usize,
) -> usize {
    let mut length = known_length;
    while length + 8 <= maximum_length {
        let current = u64::from_ne_bytes(
            data[position + length..position + length + 8]
                .try_into()
                .expect("current word bounds checked"),
        );
        let previous = u64::from_ne_bytes(
            data[candidate + length..candidate + length + 8]
                .try_into()
                .expect("candidate word bounds checked"),
        );
        if current != previous {
            break;
        }
        length += 8;
    }
    while length < maximum_length && data[position + length] == data[candidate + length] {
        length += 1;
    }
    length
}

fn consider_candidate(
    data: &[u8],
    position: usize,
    candidate: usize,
    known_length: usize,
    maximum_length: usize,
    min_match_length: usize,
    best: &mut Match,
) {
    let distance = position - candidate;
    let length = match_length(data, position, candidate, known_length, maximum_length);
    if length < min_match_length {
        return;
    }
    let gain = length as i32 - compact_match_size(distance, length) as i32;
    let best_gain = match_gain(*best);
    if gain > best_gain
        || (gain == best_gain
            && (length > best.length as usize
                || (length == best.length as usize
                    && (best.distance == 0 || distance < best.distance as usize))))
    {
        *best = Match {
            distance: distance as u32,
            length: length as u32,
        };
    }
}

#[allow(clippy::too_many_arguments)]
fn search_chain(
    data: &[u8],
    previous: &[u32],
    mut candidate: u32,
    position: usize,
    lower_bound: usize,
    known_length: usize,
    maximum_length: usize,
    min_match_length: usize,
    chain_limit: usize,
    maximum_gain: i32,
    best: &mut Match,
) -> bool {
    let mut remaining = chain_limit;
    while candidate != NONE && candidate as usize >= lower_bound && remaining > 0 {
        let candidate_position = candidate as usize;
        if data[position..position + known_length]
            == data[candidate_position..candidate_position + known_length]
        {
            consider_candidate(
                data,
                position,
                candidate_position,
                known_length,
                maximum_length,
                min_match_length,
                best,
            );
        }
        if match_gain(*best) == maximum_gain && best.length as usize == maximum_length {
            return true;
        }
        candidate = previous[candidate as usize];
        remaining -= 1;
    }
    false
}

fn search_position(
    data: &[u8],
    index: &MatchIndex,
    options: EncodeOptions,
    history_start: usize,
    position: usize,
) -> Match {
    let maximum_length = min(data.len() - position, MAX_MATCH_LENGTH);
    if maximum_length < options.min_match_length {
        return Match::default();
    }
    let lower_bound = history_start.max(position.saturating_sub(options.window_size));
    let maximum_gain = maximum_gain_upper_bound(maximum_length);
    let mut best = Match::default();

    if maximum_length >= 16
        && search_chain(
            data,
            &index.previous16,
            index.head16(data, position),
            position,
            lower_bound,
            16,
            maximum_length,
            options.min_match_length,
            options.max_match_chain,
            maximum_gain,
            &mut best,
        )
    {
        return best;
    }
    if maximum_length >= 4
        && search_chain(
            data,
            &index.previous4,
            index.head4(data, position),
            position,
            lower_bound,
            4,
            maximum_length,
            options.min_match_length,
            options.max_match_chain.min(MEDIUM_CHAIN_LIMIT),
            maximum_gain,
            &mut best,
        )
    {
        return best;
    }
    if maximum_length >= 2 {
        search_chain(
            data,
            &index.previous2,
            index.head2(data, position),
            position,
            lower_bound,
            2,
            maximum_length,
            options.min_match_length,
            options.max_match_chain,
            maximum_gain,
            &mut best,
        );
    }
    best
}

fn distance_encoding(distance: usize) -> (u8, Vec<u8>) {
    let distance_value = distance - 1;
    if distance_value <= 7 {
        return (((distance_value as u8) << 1) | 1, Vec::new());
    }
    let encoded = encode_coded_integer(distance_value);
    if encoded.len() > 1 && encoded[0] >> 1 < 8 {
        return (((encoded[0] >> 1) << 1), encoded[1..].to_vec());
    }
    (0, encoded)
}

fn encode_block(
    literals: &[u8],
    matches: &[(u32, u32)],
    output: &mut Vec<u8>,
) -> Result<(), EncodeError> {
    if literals.is_empty() {
        return Err(EncodeError::new(
            "game-compatible blocks require at least one literal",
        ));
    }
    let literal_nibble = if literals.len() <= 0x0f {
        literals.len() as u8
    } else {
        0
    };
    let match_nibble = if !matches.is_empty() && matches.len() <= 0x0f {
        matches.len() as u8
    } else {
        0
    };
    output.push((match_nibble << 4) | literal_nibble);
    if literal_nibble == 0 {
        output.extend(encode_coded_integer(literals.len()));
    }
    if match_nibble == 0 {
        output.extend(encode_coded_integer(matches.len()));
    }
    output.extend_from_slice(literals);

    for &(distance, length) in matches {
        if distance == 0 || length < 2 {
            return Err(EncodeError::new("invalid match"));
        }
        let (distance_bits, distance_extension) = distance_encoding(distance as usize);
        let length_value = length as usize - 1;
        let (length_bits, length_extension) = if length_value <= 0x0f {
            ((length_value as u8) << 4, Vec::new())
        } else {
            (0, encode_coded_integer(length_value))
        };
        output.push(length_bits | distance_bits);
        output.extend(distance_extension);
        output.extend(length_extension);
    }
    Ok(())
}

fn encode_payload_for_bias(
    data: &[u8],
    options: EncodeOptions,
    lazy_bias: i32,
) -> Result<Vec<u8>, EncodeError> {
    let history_start = options.prefix_size.saturating_sub(options.window_size);
    let mut index = MatchIndex::new(data.len());
    for position in history_start..options.prefix_size {
        index.add_position(data, position);
    }
    let mut output = Vec::new();
    let mut literal_start = options.prefix_size;
    let mut match_sequence_start: Option<usize> = None;
    let mut pending_matches: Vec<(u32, u32)> = Vec::new();
    let mut position = options.prefix_size;

    while position < data.len() {
        let current = search_position(data, &index, options, history_start, position);
        let current_gain = match_gain(current);
        let mut use_match = current.length >= 2 && current_gain > 0;
        index.add_position(data, position);
        if use_match && position + 1 < data.len() {
            let following = search_position(data, &index, options, history_start, position + 1);
            if match_gain(following) > current_gain + lazy_bias {
                use_match = false;
            }
        }
        if use_match && pending_matches.is_empty() && position == literal_start {
            use_match = false;
        }
        if !use_match {
            if !pending_matches.is_empty() {
                let sequence_start =
                    match_sequence_start.expect("pending matches require a sequence start");
                encode_block(
                    &data[literal_start..sequence_start],
                    &pending_matches,
                    &mut output,
                )?;
                literal_start = position;
                match_sequence_start = None;
                pending_matches.clear();
            }
            position += 1;
            continue;
        }

        if pending_matches.is_empty() {
            match_sequence_start = Some(position);
        }
        pending_matches.push((current.distance, current.length));
        let match_end = position + current.length as usize;
        for consumed_position in position + 1..match_end {
            index.add_position(data, consumed_position);
        }
        position = match_end;
    }

    if !pending_matches.is_empty() {
        let sequence_start =
            match_sequence_start.expect("pending matches require a sequence start");
        encode_block(
            &data[literal_start..sequence_start],
            &pending_matches,
            &mut output,
        )?;
    } else if literal_start < data.len() {
        encode_block(&data[literal_start..], &[], &mut output)?;
    }
    Ok(output)
}

pub fn encode_payload(data: &[u8], options: EncodeOptions) -> Result<Vec<u8>, EncodeError> {
    options.validate(data.len())?;
    if data.is_empty() || options.prefix_size == data.len() {
        return Ok(Vec::new());
    }
    let mut best: Option<Vec<u8>> = None;
    let first_bias = options.lazy_bias.unwrap_or(0);
    let last_bias = options.lazy_bias.unwrap_or(8);
    for lazy_bias in first_bias..=last_bias {
        let candidate = encode_payload_for_bias(data, options, i32::from(lazy_bias))?;
        let replace = best.as_ref().is_none_or(|current| {
            candidate.len() < current.len()
                || (candidate.len() == current.len() && candidate < *current)
        });
        if replace {
            best = Some(candidate);
        }
    }
    Ok(best.expect("non-empty suffix produces at least one payload"))
}

fn window_size_from_flags(flags: usize) -> usize {
    1usize << (((flags >> 1) & 0x0f) + 8)
}

fn uses_conditional_header_value(flags: usize, window_size: usize, size: usize) -> bool {
    flags & 0x40 != 0 && (window_size <= size || (flags & 0x21) != 1)
}

pub fn flags_for_size(size: usize) -> usize {
    let exponent = if size <= 1 {
        8
    } else {
        (usize::BITS - (size - 1).leading_zeros()) as usize
    }
    .clamp(8, 23);
    ((exponent - 8) << 1) | 1
}

pub fn encode_stream(
    data: &[u8],
    flags: usize,
    header_unknown_0: Option<usize>,
    header_unknown_1: usize,
    min_match_length: usize,
    max_match_chain: usize,
    lazy_bias: Option<u8>,
) -> Result<Vec<u8>, EncodeError> {
    let window_size = window_size_from_flags(flags);
    let needs_conditional = uses_conditional_header_value(flags, window_size, data.len());
    if needs_conditional != header_unknown_0.is_some() {
        return Err(EncodeError::new(
            "conditional header value does not match the selected flags",
        ));
    }
    let mut output = encode_coded_integer(data.len());
    output.extend(encode_coded_integer(flags));
    if let Some(value) = header_unknown_0 {
        output.extend(encode_coded_integer(value));
    }
    output.extend(encode_coded_integer(header_unknown_1));
    output.extend(encode_payload(
        data,
        EncodeOptions {
            window_size,
            min_match_length,
            max_match_chain,
            prefix_size: 0,
            lazy_bias,
        },
    )?);
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coded_integer_known_boundaries() {
        assert_eq!(encode_coded_integer(0), vec![0x01]);
        assert_eq!(encode_coded_integer(42), vec![0x55]);
        assert_eq!(encode_coded_integer(127), vec![0xff]);
        assert_eq!(encode_coded_integer(128), vec![0x02, 0x01]);
        assert_eq!(encode_coded_integer(16_383), vec![0xfe, 0xff]);
    }

    #[test]
    fn literal_only_fixture_is_game_compatible() {
        let encoded = encode_stream(b"abc", 1, None, 0, 2, 64, None).unwrap();
        assert_eq!(
            encoded,
            vec![0x07, 0x03, 0x01, 0x03, 0x01, b'a', b'b', b'c']
        );
    }

    #[test]
    fn repetitive_input_uses_an_overlap_match() {
        let encoded = encode_stream(&vec![b'A'; 4096], 9, None, 0, 2, 65_535, None).unwrap();
        assert!(encoded.len() < 32);
    }

    #[test]
    fn prefix_payload_still_starts_with_a_literal() {
        let data = b"abcdabcdabcdabcd";
        let payload = encode_payload(
            data,
            EncodeOptions {
                window_size: 256,
                min_match_length: 2,
                max_match_chain: 65_535,
                prefix_size: 4,
                lazy_bias: None,
            },
        )
        .unwrap();
        assert!(!payload.is_empty());
        assert_ne!(payload[0] & 0x0f, 0);
    }

    #[test]
    fn single_lazy_bias_is_a_valid_deterministic_profile() {
        let data = b"literal-abcdabcdabcdabcd-tail";
        let options = EncodeOptions {
            window_size: 256,
            min_match_length: 2,
            max_match_chain: 65_535,
            prefix_size: 0,
            lazy_bias: Some(4),
        };
        let first = encode_payload(data, options).unwrap();
        let second = encode_payload(data, options).unwrap();
        assert_eq!(first, second);
    }

    #[test]
    fn lazy_bias_outside_the_portfolio_is_rejected() {
        let error = EncodeOptions {
            window_size: 256,
            min_match_length: 2,
            max_match_chain: 64,
            prefix_size: 0,
            lazy_bias: Some(9),
        }
        .validate(16)
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "lazy bias must be between zero and eight"
        );
    }
}
