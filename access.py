"""Local prototype accounts and assignment checks. Use an identity provider before deployment."""
import argparse
import getpass
import hashlib
import hmac
import json
import secrets

from pipeline import ROOT

USERS=ROOT/'data/users.json'


def users(path=USERS):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def add_user(name,password,role,agent_id='',path=USERS):
    if not name.strip() or len(name)>100 or len(password)<12 or role not in ('agent','supervisor') or (role=='agent' and not agent_id):
        raise ValueError('Use a username, password of at least 12 characters, valid role and an agent ID for an agent account')
    stored=users(path)
    if name in stored:
        raise ValueError('Account already exists; existing credentials were preserved')
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    stored[name]={'salt':salt,'password_hash':digest,'iterations':600000,'role':role,'agent_id':agent_id}
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(stored,indent=2),encoding='utf-8')
    temporary.replace(path)


def authenticate(name,password,path=USERS):
    user=users(path).get(name)
    salt=bytes.fromhex(user['salt']) if user else b'\0'*16
    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex()
    expected=user['password_hash'] if user else '0'*64
    if not hmac.compare_digest(actual,expected) or not user:
        return None
    return {'name':name,'role':user['role'],'agent_id':user['agent_id'],'credential_version':expected}


def authorize_case(con,actor,case_id):
    if actor['role']=='supervisor':
        return
    assigned=con.execute('SELECT assigned_agent_id FROM curated.cases WHERE case_id=?',[case_id]).fetchone()
    if actor['role']!='agent' or not assigned or assigned[0]!=actor['agent_id']:
        raise PermissionError('This case is not assigned to the signed-in agent')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create'])
    parser.add_argument('--user',required=True)
    parser.add_argument('--role',choices=['agent','supervisor'],required=True)
    parser.add_argument('--agent-id',default='')
    args=parser.parse_args()
    password=getpass.getpass('New password, at least 12 characters: ')
    if password!=getpass.getpass('Confirm password: '):
        parser.error('Passwords differ')
    add_user(args.user,password,args.role,args.agent_id)
    print('Local account created. Passwords are hashed; authentication activates when the account file exists.')
