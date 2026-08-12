use std::env;
use std::fs;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::ExitCode;

use srwz_compress::{decode_stream, encode_payload, encode_stream, flags_for_size, EncodeOptions};

#[derive(Debug)]
struct Arguments {
    mode: String,
    input: PathBuf,
    output: PathBuf,
    flags: Option<usize>,
    header_unknown_0: Option<usize>,
    header_unknown_1: usize,
    window_size: Option<usize>,
    prefix_size: usize,
    min_match_length: usize,
    max_match_chain: usize,
    lazy_bias: Option<u8>,
    max_output_size: Option<usize>,
}

fn parse_usize(name: &str, value: Option<String>) -> Result<usize, String> {
    let raw = value.ok_or_else(|| format!("missing value for {name}"))?;
    raw.parse::<usize>()
        .map_err(|_| format!("invalid integer for {name}: {raw}"))
}

fn parse_arguments() -> Result<Arguments, String> {
    let mut values = env::args().skip(1);
    let mode = values.next().ok_or_else(|| {
        "usage: srwz-compress <encode|payload> --input PATH --output PATH [options]".to_owned()
    })?;
    if mode != "encode" && mode != "payload" {
        return Err(format!("unknown mode: {mode}"));
    }

    let mut input = None;
    let mut output = None;
    let mut flags = None;
    let mut header_unknown_0 = None;
    let mut header_unknown_1 = 0;
    let mut window_size = None;
    let mut prefix_size = 0;
    let mut min_match_length = 2;
    let mut max_match_chain = 65_535;
    let mut lazy_bias = None;
    let mut max_output_size = None;

    while let Some(option) = values.next() {
        match option.as_str() {
            "--input" => input = values.next().map(PathBuf::from),
            "--output" => output = values.next().map(PathBuf::from),
            "--flags" => flags = Some(parse_usize("--flags", values.next())?),
            "--header-unknown-0" => {
                header_unknown_0 = Some(parse_usize("--header-unknown-0", values.next())?)
            }
            "--header-unknown-1" => {
                header_unknown_1 = parse_usize("--header-unknown-1", values.next())?
            }
            "--window-size" => window_size = Some(parse_usize("--window-size", values.next())?),
            "--prefix-size" => prefix_size = parse_usize("--prefix-size", values.next())?,
            "--min-match-length" => {
                min_match_length = parse_usize("--min-match-length", values.next())?
            }
            "--max-match-chain" => {
                max_match_chain = parse_usize("--max-match-chain", values.next())?
            }
            "--lazy-bias" => {
                let value = parse_usize("--lazy-bias", values.next())?;
                if value > 8 {
                    return Err("--lazy-bias must be between zero and eight".to_owned());
                }
                lazy_bias = Some(value as u8);
            }
            "--max-output-size" => {
                max_output_size = Some(parse_usize("--max-output-size", values.next())?)
            }
            _ => return Err(format!("unknown option: {option}")),
        }
    }

    Ok(Arguments {
        mode,
        input: input.ok_or_else(|| "--input is required".to_owned())?,
        output: output.ok_or_else(|| "--output is required".to_owned())?,
        flags,
        header_unknown_0,
        header_unknown_1,
        window_size,
        prefix_size,
        min_match_length,
        max_match_chain,
        lazy_bias,
        max_output_size,
    })
}

fn run() -> Result<(), String> {
    if env::args().nth(1).as_deref() == Some("decode-stdio") {
        let mut data = Vec::new();
        std::io::stdin()
            .read_to_end(&mut data)
            .map_err(|error| format!("failed to read stdin: {error}"))?;
        let decoded = decode_stream(&data, 256 * 1024 * 1024, 10, 10_000_000)
            .map_err(|error| error.to_string())?;
        let unknown_0 = decoded.header_unknown_0.unwrap_or(u64::MAX as usize) as u64;
        let fields = [
            decoded.consumed as u64,
            decoded.declared_size as u64,
            decoded.flags as u64,
            decoded.header_size as u64,
            decoded.window_size as u64,
            unknown_0,
            decoded.header_unknown_1 as u64,
            decoded.output.len() as u64,
        ];
        let mut stdout = std::io::stdout().lock();
        stdout
            .write_all(b"SRWZD001")
            .map_err(|error| format!("failed to write stdout: {error}"))?;
        for field in fields {
            stdout
                .write_all(&field.to_le_bytes())
                .map_err(|error| format!("failed to write stdout: {error}"))?;
        }
        stdout
            .write_all(&decoded.output)
            .map_err(|error| format!("failed to write stdout: {error}"))?;
        return Ok(());
    }
    let arguments = parse_arguments()?;
    let data =
        fs::read(&arguments.input).map_err(|error| format!("failed to read input: {error}"))?;
    let encoded = if arguments.mode == "encode" {
        if arguments.window_size.is_some() || arguments.prefix_size != 0 {
            return Err("--window-size/--prefix-size are payload-mode options".to_owned());
        }
        let flags = arguments
            .flags
            .unwrap_or_else(|| flags_for_size(data.len()));
        encode_stream(
            &data,
            flags,
            arguments.header_unknown_0,
            arguments.header_unknown_1,
            arguments.min_match_length,
            arguments.max_match_chain,
            arguments.lazy_bias,
        )
        .map_err(|error| error.to_string())?
    } else {
        if arguments.flags.is_some() || arguments.header_unknown_0.is_some() {
            return Err("--flags/--header-unknown-0 are encode-mode options".to_owned());
        }
        let window_size = arguments
            .window_size
            .ok_or_else(|| "--window-size is required in payload mode".to_owned())?;
        encode_payload(
            &data,
            EncodeOptions {
                window_size,
                min_match_length: arguments.min_match_length,
                max_match_chain: arguments.max_match_chain,
                prefix_size: arguments.prefix_size,
                lazy_bias: arguments.lazy_bias,
            },
        )
        .map_err(|error| error.to_string())?
    };
    if let Some(limit) = arguments.max_output_size {
        if encoded.len() > limit {
            return Err(format!(
                "encoded output size {} exceeds limit {limit}",
                encoded.len()
            ));
        }
    }
    fs::write(&arguments.output, &encoded)
        .map_err(|error| format!("failed to write output: {error}"))?;
    println!(
        "mode={} input={} output={}",
        arguments.mode,
        data.len(),
        encoded.len()
    );
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("srwz-compress: {error}");
            ExitCode::FAILURE
        }
    }
}
