"""Host-only initialization; never exposed as an HTTP route."""
import argparse
import getpass
import os
from pathlib import Path
from app.services.team_store import TeamStore

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--state',type=Path,default=Path(os.environ.get('DATAFLOW_TEAM_DIR','data/collaboration')));p.add_argument('--legacy-root',type=Path,default=Path.cwd());args=p.parse_args()
    first=getpass.getpass('管理员密码（至少 12 字符）: ')
    if first!=getpass.getpass('再次输入: '):raise SystemExit('密码不一致')
    TeamStore(args.state).initialize(args.name,first,args.legacy_root)
    print('管理员与默认项目初始化完成。请在浏览器登录。')
