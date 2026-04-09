import urllib.request
import json
import re
import os
import subprocess

PAGES = [
    {"name": "ISG 2.5", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/integrated-secure-gateway/2-5/25-release-notes/25-whats-new.html"},
    {"name": "Edge SWG 7.3", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/edge-swg/7-3/what-s-new-in-proxysg-7-3/features-summary-table.html"},
    {"name": "Edge SWG 7.4", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/edge-swg/7-4/what-s-new-in-proxysg-7-4/74-features-summary-table.html"},
    {"name": "Content Analysis 3.2", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/content-analysis/3-2/rn-cas-3-2-x-intro1.html"},
    {"name": "Content Analysis 4.1", "url": "https://techdocs.broadcom.com/us/en/symantec-security-software/web-and-network-security/content-analysis/4-1/ca-41-rns/changes-411.html"}
]

STATE_FILE = "state.json"

def get_last_updated(url):
    # 보안 차단을 피하기 위해 실제 크롬 브라우저처럼 User-Agent 위장
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        match = re.search(r'Last Updated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', html)
        if match:
            return match.group(1)
        else:
            print("  -> [경고] 페이지 접속은 성공했으나, 'Last Updated' 날짜를 찾을 수 없습니다.")
            return "-"
    except Exception as e:
        print(f"  -> [에러] 페이지 접근 실패: {e}")
        return "-"

def main():
    print("Broadcom 문서 업데이트 확인 스크립트 실행 시작...\n")
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    else:
        state = {}

    updates = []
    state_changed = False

    for page in PAGES:
        name = page["name"]
        url = page["url"]
        
        print(f"[{name}] 페이지 확인 중...")
        current_date = get_last_updated(url)
        print(f"  -> 현재 확인된 날짜: {current_date}")
        
        previous_date = state.get(name, "없음")
        print(f"  -> 기존 저장된 날짜: {previous_date}\n")

        # 기존 날짜와 다르면 무조건 상태 변경 (에러가 나서 "-"로 찍혀도 파일은 무조건 생성하도록)
        if current_date != previous_date:
            state[name] = current_date
            state_changed = True
            
            # 알림은 최초 실행이 아니고, 에러("-")가 아닐 때만 발송
            if previous_date != "없음" and current_date != "-":
                updates.append({
                    "name": name,
                    "date": current_date,
                    "url": url
                })

    if state_changed:
        print("💡 상태가 변경되어 state.json 파일을 생성/저장합니다.")
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    else:
        print("💡 변경사항이 없습니다.")

    # 환경변수 기록 (워크플로우에서 커밋 여부를 결정하도록 전달)
    env_file = os.environ.get('GITHUB_ENV')
    if env_file:
        if state_changed:
            with open(env_file, 'a') as f:
                f.write("STATE_CHANGED=true\n")
        if updates:
            with open(env_file, 'a') as f:
                f.write("UPDATE_FOUND=true\n")

    if not updates:
        print("\n🔔 새롭게 알림을 보낼 업데이트 내용이 없습니다.")
        return

    print(f"\n🔔 {len(updates)}개의 업데이트 알림 발송 중...")
    
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
        print("  -> GitHub Issue 생성 완료")
    except Exception as e:
        print(f"  -> GitHub Issue 생성 실패: {e}")

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
            headers={'Accept': 'application/vnd.tosslab.jandi-v2+json', 'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            urllib.request.urlopen(req)
            print("  -> 잔디 알림 발송 완료")
        except Exception as e:
            print(f"  -> 잔디 알림 실패: {e}")

if __name__ == "__main__":
    main()
