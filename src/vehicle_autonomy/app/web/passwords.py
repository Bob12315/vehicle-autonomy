"""Private salted password verifier for the local browser login."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat

ITERATIONS=600_000


def validate(password):
    if type(password) is not str or not 8<=len(password)<=256:
        raise ValueError('密码长度须为 8 至 256 个字符。')


@dataclass(frozen=True)
class PasswordVerifier:
    salt: bytes
    digest: bytes

    def verify(self,password):
        validate(password)
        actual=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),self.salt,ITERATIONS)
        return hmac.compare_digest(actual,self.digest)


def load_password(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or info.st_nlink!=1:
            raise ValueError('password verifier must be an owned private regular file (0600)')
        value=json.loads(stream.read(2049))
    if type(value) is not dict or set(value)!={'schema','algorithm','iterations','salt','digest'} or value['schema']!=1 or value['algorithm']!='pbkdf2-sha256' or type(value['iterations']) is not int or value['iterations']!=ITERATIONS:
        raise ValueError('unsupported password verifier')
    try:salt=bytes.fromhex(value['salt']);digest=bytes.fromhex(value['digest'])
    except (ValueError,TypeError):raise ValueError('invalid password verifier') from None
    if len(salt)!=32 or len(digest)!=32:raise ValueError('invalid password verifier length')
    return PasswordVerifier(salt,digest)


def set_password(path,password):
    validate(password);path=Path(path)
    if path.exists() or path.is_symlink():load_password(path)  # refuse replacing unowned/linked files
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    salt=secrets.token_bytes(32)
    value=dict(schema=1,algorithm='pbkdf2-sha256',iterations=ITERATIONS,salt=salt.hex(),
        digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,ITERATIONS).hex())
    temporary=path.with_name(path.name+'.'+secrets.token_hex(12)+'.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(descriptor,'w') as stream:
            json.dump(value,stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
