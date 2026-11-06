
void FUN_00148420(int param_1,int param_2,long param_3)

{
  undefined1 uVar1;
  int *piVar2;
  short *psVar3;
  int *piVar4;
  int iVar5;
  
  if (0x326 < param_2) {
    param_2 = 0x326;
  }
  param_1 = param_1 * 0x118;
  piVar4 = (int *)(param_1 + 0x5388d0);
  *(int *)(param_1 + 0x538978) = param_2 * 0x44 + 0x7232e0;
  *(undefined1 *)(param_1 + 0x5389d5) = 0;
  *(undefined1 *)(param_1 + 0x5389d6) = 0;
  *(undefined1 *)(param_1 + 0x5389d7) = 0;
  *(undefined1 *)(param_1 + 0x5389d8) = 0;
  *(byte *)(param_1 + 0x538999) = *(byte *)(param_1 + 0x538999) & 0xbf | 0x40;
  *(byte *)(param_1 + 0x538999) = *(byte *)(param_1 + 0x538999) & 0xfe;
  *(undefined4 *)(param_1 + 0x53899c) = 0;
  *(undefined2 *)(param_1 + 0x5389ca) = 0xffff;
  *(undefined4 *)(param_1 + 0x5389a8) = *(undefined4 *)(param_1 + 0x5389a4);
  *(undefined2 *)(param_1 + 0x5389c2) = *(undefined2 *)(param_1 + 0x5389c0);
  *(undefined1 *)(param_1 + 0x5389e1) = *(undefined1 *)(*(int *)(param_1 + 0x538978) + 0x39);
  thunk_FUN_0028c7b0(piVar4);
  iVar5 = 0;
  psVar3 = (short *)(**(short **)(param_1 + 0x538978) * 0x2a + 0x700c30);
  piVar2 = piVar4;
  do {
    *piVar2 = *psVar3 * 0x24 + 0x7090a0;
    uVar1 = FUN_00148cf0(piVar4,piVar2);
    iVar5 = iVar5 + 1;
    *(undefined1 *)(piVar2 + 1) = uVar1;
    psVar3 = psVar3 + 1;
    piVar2 = piVar2 + 2;
  } while (iVar5 < 0x15);
  if (param_3 != 0) {
    FUN_001483b0(piVar4);
  }
  *(undefined2 *)(param_1 + 0x5389cc) = 0;
  *(undefined4 *)(param_1 + 0x538980) = 0;
  *(undefined4 *)(param_1 + 0x538984) = 0;
  *(undefined4 *)(param_1 + 0x538988) = 0;
  *(undefined4 *)(param_1 + 0x53898c) = 0;
  *(undefined4 *)(param_1 + 0x538990) = 0;
  *(undefined4 *)(param_1 + 0x538994) = 0;
  return;
}

