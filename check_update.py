import urllib.request
import re
import os

url = "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/integrated-secure-gateway/2-5/25-release-notes/25-whats-new.html"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    match = re.search(r'Last Updated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', html)
    current_date = match.group(1) if match else "-"
except Exception:
    current_date = "-"

# 날짜를 찾지 못했거나 에러가 발생하여 "-"인 경우 그냥 "-"로 표시
if current_date == "-":
    print("-")
    exit(0)

state_file = "last_updated.txt"
previous_date = "-"

if os.path.exists(state_file):
    with open(state_file, "r") as f:
        previous_date = f.read().strip()

if current_date != previous_date:
    print("업데이트가 발견되었습니다!")
    # GitHub Actions의 환경 변수로 상태 전달
    with open(os.environ.get('GITHUB_ENV', '.env'), 'a') as env_file:
        env_file.write("UPDATE_FOUND=true\n")
        env_file.write(f"NEW_DATE={current_date}\n")
    
    # 새로운 날짜로 파일 덮어쓰기
    with open(state_file, "w") as f:
        f.write(current_date)
else:
    print("새로운 업데이트가 없습니다.")
