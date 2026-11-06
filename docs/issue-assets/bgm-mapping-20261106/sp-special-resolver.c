
short FUN_00182c10(undefined8 param_1,short param_2,short param_3,undefined8 param_4,short param_5,
                  short param_6)

{
  long lVar1;
  short *psVar2;
  
  psVar2 = (short *)&DAT_0046c3d0;
  do {
    lVar1 = ((long)*psVar2 << 0x30) >> 0x31;
    if (lVar1 == -1) {
      return -1;
    }
    if ((long)(char)psVar2[1] < 0) {
      if ((long)(char)*psVar2 << 0x3f < 0) {
        if ((param_2 == lVar1) || (param_5 == lVar1)) {
          return psVar2[2];
        }
      }
      else if (((short)param_1 == lVar1) || ((short)param_4 == lVar1)) {
        return psVar2[2];
      }
    }
    else if (-1 < (long)(char)*psVar2 << 0x3f) {
      if ((short)param_1 == lVar1) {
        if ((long)param_3 == -1) {
          lVar1 = FUN_00266ce0(param_1);
          if (lVar1 != 0) {
            return psVar2[2];
          }
        }
        else if ((long)(char)psVar2[1] == (long)param_3) {
          return psVar2[2];
        }
      }
      if ((long)(short)param_4 == ((long)*psVar2 << 0x30) >> 0x31) {
        if ((long)param_6 == -1) {
          lVar1 = FUN_00266ce0(param_4,(char)psVar2[1]);
          if (lVar1 != 0) {
            return psVar2[2];
          }
        }
        else if ((long)(char)psVar2[1] == (long)param_6) {
          return psVar2[2];
        }
      }
    }
    psVar2 = psVar2 + 3;
  } while( true );
}

