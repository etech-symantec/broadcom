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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        
        # 1. HTML 태그 싹 지우기 (태그 때문에 문장이 끊어지는 현상 완벽 방지)
        clean_text = re.sub(r'<[^>]+>', ' ', html)
        # 여러 칸의 띄어쓰기를 한 칸으로 압축
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        # 2. 'Last Updated' 텍스트 찾기 (콜론이나 띄어쓰기 예외도 모두 허용)
        match = re.search(r'Last Updated\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', clean_text, re.IGNORECASE)
        if match:
            return match.group(1)
            
        # 3. 문서에 따라 'Updated: ' 형태로 적힌 경우도 대비
        match_alt = re.search(r'Updated\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', clean_text, re.IGNORECASE)
        if match_alt:
            return match_alt.group(1)
            
        # 4. 본문에 날짜가 아예 안보인다면, 검색엔진용 메타 태그(meta tag)에서 변경 날짜 찾기
        meta_match = re.search(r'<meta[^>]+(?:name|property)=["\']?(?:article:modified_time|last-modified|date|updated)["\']?[^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if meta_match:
            date_str = meta_match.group(1).split('T')[0] # 불필요한 시간 제거 (YYYY-MM-DD 만 남김)
            print("  -> [안내] 본문 대신 숨겨진 메타 태그에서 날짜를 찾았습니다.")
            return date_str

        print("  -> [경고] 태그를 모두 지우고 검사했음에도 날짜 텍스트를 찾을 수 없습니다.")
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

        if current_date != previous_date:
            state[name] = current_date
            state_changed = True
            
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
                "description": f"새로운 날짜: **{u['date']}**\n[문서 바로가기]({u['url']})",
                "imageUrl": ""
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
