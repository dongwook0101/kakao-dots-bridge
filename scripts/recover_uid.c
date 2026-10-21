#include <CommonCrypto/CommonDigest.h>
#include <dispatch/dispatch.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
// Same SHA-512 preimage method documented by MIT-licensed kakaocli DeviceInfo.
int main(int argc, char **argv) {
 if(argc != 3 || strlen(argv[1]) != 128) return 2;
 unsigned char target[64];
 for(int i=0;i<64;i++){ unsigned int b; if(sscanf(argv[1]+2*i,"%2x",&b)!=1)return 2;target[i]=(unsigned char)b; }
 const unsigned char *targetPtr=target;
 unsigned long long end=strtoull(argv[2],NULL,10);
 __block atomic_ullong found=0;
 dispatch_apply(8,dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^(size_t worker){
  char s[32];unsigned char hash[64];
  for(unsigned long long n=worker;n<end;n+=8){
   if((n & 8191)==worker && atomic_load(&found))break;
   int len=snprintf(s,sizeof(s),"%llu",n);
   CC_SHA512(s,(CC_LONG)len,hash);
   if(!memcmp(hash,targetPtr,64)){atomic_store(&found,n+1);break;}
  }
 });
 if(atomic_load(&found)){printf("%llu\n",atomic_load(&found)-1);return 0;}
 return 1;
}
