#!/usr/bin/env python3
import paramiko, socket, sys

proxy_host = '127.0.0.1'
proxy_port = 18080
target_host = '8.141.109.234'
target_port = 22

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(10)
s.connect((proxy_host, proxy_port))
s.sendall(f'CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n\r\n'.encode())
response = b''
while b'\r\n\r\n' not in response:
    response += s.recv(4096)
s.settimeout(120)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=target_host, port=target_port, username='root', password='cc159.00', sock=s, timeout=30, auth_timeout=30)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    return stdout.read().decode('utf-8', errors='replace'), stderr.read().decode('utf-8', errors='replace')

# 1. mapping_config.json 表结构
print("=" * 60)
print(" mapping_config.json -> 表映射")
print("=" * 60)
out, _ = run('python3 << "PYEOF"\nimport json\nwith open("/opt/power-trading/mapping_config.json", "r", encoding="utf-8") as f:\n    config = json.load(f)\nfor tab in config.get("tabs", []):\n    print(f"  {tab[\'tab_name\']} -> {tab[\'target_table\']} (时间列: {tab.get(\'time_column\', \'-\')}, 字段: {len(tab.get(\'field_mapping\', {}))})")\nprint(f"  共 {len(config.get(\'tabs\', []))} 个表")\nPYEOF')
print(out)

# 2. MySQL 数据量
print()
print("=" * 60)
print(" MySQL 各表行数")
print("=" * 60)
out, _ = run('''source /opt/power-trading/.env 2>/dev/null
DB_PASS=$(grep DB_PASSWORD /opt/power-trading/.env | cut -d= -f2)
mysql -u root -p"$DB_PASS" -h 127.0.0.1 -D henan_power -e "
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'henan_power'
ORDER BY TABLE_NAME;" 2>/dev/null''')
print(out)

# 3. 是否有预测表
print()
print("=" * 60)
print(" 预测相关表")
print("=" * 60)
out, _ = run('''source /opt/power-trading/.env 2>/dev/null
DB_PASS=$(grep DB_PASSWORD /opt/power-trading/.env | cut -d= -f2)
mysql -u root -p"$DB_PASS" -h 127.0.0.1 -D henan_power -e "SHOW TABLES LIKE 'forecast_%';" 2>/dev/null''')
print(out)

# 4. load_info 表抽样检查（实际）
print()
print("=" * 60)
print(" load_info（实际负荷）前 3 行抽样")
print("=" * 60)
out, _ = run('''source /opt/power-trading/.env 2>/dev/null
DB_PASS=$(grep DB_PASSWORD /opt/power-trading/.env | cut -d= -f2)
mysql -u root -p"$DB_PASS" -h 127.0.0.1 -D henan_power -e "SELECT * FROM load_info ORDER BY id DESC LIMIT 3;" 2>/dev/null''')
print(out)

# 5. 看预测表的样本数据（如果有）
print()
print("=" * 60)
print(" forecast_load_info（预测负荷）前 3 行抽样")
print("=" * 60)
out, _ = run('''source /opt/power-trading/.env 2>/dev/null
DB_PASS=$(grep DB_PASSWORD /opt/power-trading/.env | cut -d= -f2)
mysql -u root -p"$DB_PASS" -h 127.0.0.1 -D henan_power -e "SELECT * FROM forecast_load_info ORDER BY id DESC LIMIT 3;" 2>/dev/null''')
print(out)

ssh.close()
