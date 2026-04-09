import urllib.request
import json
import re
import os
import subprocess

# 모니터링할 대상 페이지 목록
PAGES = [
    {"name": "ISG 2.5", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/integrated-secure-gateway/2-5/25-release-notes/25-whats-new.html"},
    {"name": "Edge SWG 7.3", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/edge-swg/7-3/what-s-new-in-proxysg-7-3/features-summary-table.html"},
    {"name": "Edge SWG 7.4", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/edge-swg/7-4/what-s-new-in-proxysg-7-4/74-features-summary-table.html"},
    {"name": "Content Analysis 3.2", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/content-analysis/3-2/rn-cas-3-2-x-intro1.html"},
    {"name": "Content Analysis 4.1", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/content-analysis/4-1/ca-41-rns/changes-411.html"}
]

STATE_FILE = "state.json"

def get_last_updated(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        match = re.search(r'Last Updated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', html)
        return match.group(1) if match else "-"
    except Exception:
        return "-"

def main():
    # 이전 상태 불러오기
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    else:
        state = {}

    updates = []

    for page in PAGES:
        name = page["name"]
        url = page["url"]
        current_date = get_last_updated(url)
        
        if current_date == "-":
            continue

        previous_date = state.get(name, "-")

        # 업데이트 여부 확인
        if current_date != previous_date:
            state[name] = current_date
            
            # 이전 기록이 없는(최초 실행) 경우는 알림을 보내지 않음 (알림 폭탄 방지)
            if previous_date != "-":
                updates.append({
                    "name": name,
                    "date": current_date,
                    "url": url
                })

    # 변경된 상태 저장
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

    # 업데이트가 없으면 종료
    if not updates:
        print("새로운 업데이트가 없습니다.")
        return

    print(f"{len(updates)}개의 업데이트 발견!")
    
    # 워크플로우에 업데이트가 있었음을 알림
    env_file = os.environ.get('GITHUB_ENV')
    if env_file:
        with open(env_file, 'a') as f:
            f.write("UPDATE_FOUND=true\n")

    # 1. GitHub Issue 생성
    issue_body = "다음 문서들의 업데이트가 확인되었습니다.\n\n"
    for u in updates:
        issue_body += f"- **{u['name']}**: {u['date']} ([링크]({u['url']}))\n"
        
    try:
        subprocess.run([
            "gh", "issue", "create", 
            "--title", f"Broadcom 문서 업데이트 알림 ({len(updates)}건)", 
            "--body", issue_body
        ], check=True)
        print("GitHub Issue 생성 완료")
    except Exception as e:
        print(f"Issue 생성 실패: {e}")

    # 2. 잔디(JANDI) 웹훅 발송
    jandi_url = os.environ.get('JANDI_WEBHOOK_URL')
    if jandi_url:
        connect_info = []
        for u in updates:
            connect_info.append({
                "title": f"[{u['name']}] 업데이트",
                "description": f"새로운 날짜: **{u['date']}**\n[문서 바로가기]({u['url']})"
            })
            
        payload = {
            "body": "📢 Broadcom 문서 업데이트 알림",
            "connectColor": "#00C362",
            "connectInfo": connect_info
        }
        
        req = urllib.request.Request(
            jandi_url, 
            data=json.dumps(payload).encode('utf-8'), 
            headers={
                'Accept': 'application/vnd.tosslab.jandi-v2+json', 
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        try:
            urllib.request.urlopen(req)
            print("잔디 알림 발송 완료")
        except Exception as e:
            print(f"잔디 알림 실패: {e}")

if __name__ == "__main__":
    main()
