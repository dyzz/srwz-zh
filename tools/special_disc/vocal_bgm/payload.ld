ENTRY(hook_update)
SECTIONS { . = 0x8c0000; .text : { *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) *(.sdata*) } . = ALIGN(64); __bss_start = .; .bss : { *(.bss*) *(.sbss*) *(COMMON) } __end = .; /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.eh_frame*) } }
