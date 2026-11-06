
short FUN_001811f0(int param_1,int param_2)

{
  long lVar1;
  ulong uVar2;
  short *psVar3;
  
  psVar3 = (short *)&DAT_00411260;
  do {
    uVar2 = ((long)*psVar3 << 0x30) >> 0x31;
    if (uVar2 == 0xffffffffffffffff) {
      return -1;
    }
    if ((char)psVar3[1] < '\0') {
      if ((long)(char)*psVar3 << 0x3f < 0) {
        if ((*(ushort *)**(undefined4 **)(*(int *)(param_1 + 8) + 0xb0) == uVar2) ||
           (*(ushort *)**(undefined4 **)(*(int *)(param_2 + 8) + 0xb0) == uVar2)) {
          return psVar3[2];
        }
      }
      else if (((long)**(short **)(*(int *)(param_1 + 8) + 0xa8) == uVar2) ||
              ((long)**(short **)(*(int *)(param_2 + 8) + 0xa8) == uVar2)) {
        return psVar3[2];
      }
    }
    else if (-1 < (long)(char)*psVar3 << 0x3f) {
      if (((long)**(short **)(*(int *)(param_1 + 8) + 0xa8) == uVar2) &&
         (lVar1 = FUN_002604b0(), lVar1 != 0)) {
        return psVar3[2];
      }
      lVar1 = (long)**(short **)(*(int *)(param_2 + 8) + 0xa8);
      if ((lVar1 == ((long)*psVar3 << 0x30) >> 0x31) &&
         (lVar1 = FUN_002604b0(lVar1,(char)psVar3[1]), lVar1 != 0)) {
        return psVar3[2];
      }
    }
    psVar3 = psVar3 + 3;
  } while( true );
}

