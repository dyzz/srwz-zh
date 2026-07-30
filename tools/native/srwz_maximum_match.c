/*
 * Optional accelerator for the clean-room SRWZ maximum match table.
 *
 * This source is independently authored from documented format behavior. It
 * does not contain upstream decompiled source and never reads files itself.
 */

#include <stdint.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(_WIN32)
#define SRWZ_EXPORT __declspec(dllexport)
#else
#define SRWZ_EXPORT __attribute__((visibility("default")))
#endif

static uint32_t coded_integer_size(uint32_t value) {
    uint32_t size = 1;
    while (value >= 0x80) {
        value >>= 7;
        size += 1;
    }
    return size;
}

static uint32_t compact_match_size(uint32_t distance, uint32_t length) {
    uint32_t distance_value = distance - 1;
    uint32_t distance_extension_size = 0;
    uint32_t groups;
    uint32_t top_group;
    uint32_t length_extension_size;

    if (distance_value > 7) {
        groups = coded_integer_size(distance_value);
        top_group = distance_value >> (7 * (groups - 1));
        distance_extension_size =
            groups > 1 && top_group < 8 ? groups - 1 : groups;
    }
    length_extension_size =
        length - 1 <= 0x0f ? 0 : coded_integer_size(length - 1);
    return 1 + distance_extension_size + length_extension_size;
}

static int32_t maximum_gain_upper_bound(uint32_t maximum_length) {
    int32_t short_gain;
    int32_t long_gain;

    if (maximum_length < 2) {
        return 0;
    }
    short_gain = (int32_t)(
        (maximum_length < 16 ? maximum_length : 16) - 1
    );
    if (maximum_length <= 16) {
        return short_gain;
    }
    long_gain = (int32_t)(
        maximum_length - 1 - coded_integer_size(maximum_length - 1)
    );
    return short_gain > long_gain ? short_gain : long_gain;
}

struct match_context {
    const uint8_t *data;
    const int32_t *previous;
    uint32_t size;
    uint32_t history_start;
    uint32_t window_size;
    uint32_t min_match_length;
    uint32_t max_match_chain;
    uint32_t prefix_size;
    uint32_t *distances;
    uint32_t *lengths;
    int32_t *gains;
    _Atomic uint32_t next_position;
};

static uint32_t match_length(
    const uint8_t *data,
    uint32_t position,
    uint32_t candidate,
    uint32_t maximum_length
) {
    uint32_t length = 2;
    while (length + sizeof(uint64_t) <= maximum_length) {
        uint64_t current_word;
        uint64_t candidate_word;
        memcpy(&current_word, data + position + length, sizeof(uint64_t));
        memcpy(&candidate_word, data + candidate + length, sizeof(uint64_t));
        if (current_word != candidate_word) {
            break;
        }
        length += sizeof(uint64_t);
    }
    while (
        length < maximum_length
        && data[position + length] == data[candidate + length]
    ) {
        length += 1;
    }
    return length;
}

static void search_position(
    const struct match_context *context,
    uint32_t position
) {
    int32_t candidate = context->previous[position];
    uint32_t maximum_length = context->size - position;
    uint32_t lower_bound;
    uint32_t chain_remaining;
    uint32_t best_distance = 0;
    uint32_t best_length = 0;
    int32_t best_gain = 0;
    int32_t maximum_gain;

    if (maximum_length > 0x00ffffff) {
        maximum_length = 0x00ffffff;
    }
    if (
        maximum_length < context->min_match_length
        || candidate < (int32_t)context->history_start
    ) {
        return;
    }
    lower_bound =
        position > context->window_size
        ? position - context->window_size
        : context->history_start;
    if (lower_bound < context->history_start) {
        lower_bound = context->history_start;
    }
    chain_remaining = position - lower_bound;
    if (chain_remaining > context->max_match_chain) {
        chain_remaining = context->max_match_chain;
    }
    maximum_gain = maximum_gain_upper_bound(maximum_length);

    while (
        candidate >= (int32_t)lower_bound && chain_remaining > 0
    ) {
        uint32_t distance = position - (uint32_t)candidate;
        uint32_t length = match_length(
            context->data,
            position,
            (uint32_t)candidate,
            maximum_length
        );
        int32_t gain;

        if (length >= context->min_match_length) {
            gain = (int32_t)length
                - (int32_t)compact_match_size(distance, length);
            if (
                gain > best_gain
                || (
                    gain == best_gain
                    && (
                        length > best_length
                        || (
                            length == best_length
                            && (
                                best_distance == 0
                                || distance < best_distance
                            )
                        )
                    )
                )
            ) {
                best_distance = distance;
                best_length = length;
                best_gain = gain;
                if (
                    best_gain == maximum_gain
                    && best_length == maximum_length
                ) {
                    break;
                }
            }
        }
        candidate = context->previous[candidate];
        chain_remaining -= 1;
    }
    if (best_gain > 0) {
        context->distances[position] = best_distance;
        context->lengths[position] = best_length;
        context->gains[position] = best_gain;
    }
}

static void *search_worker(void *raw_context) {
    struct match_context *context = (struct match_context *)raw_context;
    const uint32_t batch_size = 64;
    uint32_t start;

    while (
        (start = atomic_fetch_add(
            &context->next_position,
            batch_size
        )) < context->size
    ) {
        uint32_t end = start + batch_size;
        uint32_t position;
        if (end > context->size) {
            end = context->size;
        }
        for (position = start; position < end; position += 1) {
            search_position(context, position);
        }
    }
    return NULL;
}

SRWZ_EXPORT int srwz_maximum_match_table(
    const uint8_t *data,
    uint32_t size,
    uint32_t window_size,
    uint32_t min_match_length,
    uint32_t max_match_chain,
    uint32_t prefix_size,
    uint32_t *distances,
    uint32_t *lengths,
    int32_t *gains
) {
    int32_t *heads;
    int32_t *previous;
    uint32_t history_start;
    uint32_t position;
    uint32_t index;
    long detected_cpus;
    uint32_t thread_count;
    pthread_t threads[7];
    uint32_t created_threads = 0;
    struct match_context context;

    if (
        data == NULL || distances == NULL || lengths == NULL || gains == NULL
        || prefix_size > size || min_match_length < 2
        || max_match_chain == 0 || window_size == 0
    ) {
        return 1;
    }
    heads = (int32_t *)malloc(65536 * sizeof(int32_t));
    previous = (int32_t *)malloc((size == 0 ? 1 : size) * sizeof(int32_t));
    if (heads == NULL || previous == NULL) {
        free(heads);
        free(previous);
        return 2;
    }
    for (index = 0; index < 65536; index += 1) {
        heads[index] = -1;
    }
    for (index = 0; index < size; index += 1) {
        previous[index] = -1;
        distances[index] = 0;
        lengths[index] = 0;
        gains[index] = 0;
    }

    history_start =
        prefix_size > window_size ? prefix_size - window_size : 0;
    for (position = history_start; position < size; position += 1) {
        uint32_t next_byte =
            position + 1 < size ? data[position + 1] : 0;
        uint32_t key = ((uint32_t)data[position] << 8) | next_byte;
        int32_t candidate = heads[key];

        previous[position] = candidate;
        heads[key] = (int32_t)position;
    }

    context.data = data;
    context.previous = previous;
    context.size = size;
    context.history_start = history_start;
    context.window_size = window_size;
    context.min_match_length = min_match_length;
    context.max_match_chain = max_match_chain;
    context.prefix_size = prefix_size;
    context.distances = distances;
    context.lengths = lengths;
    context.gains = gains;
    atomic_init(&context.next_position, prefix_size);

    detected_cpus = sysconf(_SC_NPROCESSORS_ONLN);
    thread_count = detected_cpus > 0 ? (uint32_t)detected_cpus : 1;
    if (thread_count > 8) {
        thread_count = 8;
    }
    if (size - prefix_size < 4096) {
        thread_count = 1;
    }
    while (created_threads + 1 < thread_count) {
        if (
            pthread_create(
                &threads[created_threads],
                NULL,
                search_worker,
                &context
            ) != 0
        ) {
            break;
        }
        created_threads += 1;
    }
    search_worker(&context);
    for (index = 0; index < created_threads; index += 1) {
        pthread_join(threads[index], NULL);
    }

    free(previous);
    free(heads);
    return 0;
}
