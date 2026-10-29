#!/usr/bin/env python3
"""Inject tokens from tokens.json into 9router database."""
import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

def main():
    ap = argparse.ArgumentParser(description="Inject Kiro tokens into 9router DB")
    ap.add_argument("--tokens", default="tokens.json", help="tokens JSON file")
    ap.add_argument("--db", default="~/.9router/db/data.sqlite", help="9router database path")
    args = ap.parse_args()

    import os
    db_path = os.path.expanduser(args.db)
    
    if not os.path.exists(args.tokens):
        print(f"Error: {args.tokens} not found")
        return
    
    if not os.path.exists(db_path):
        print(f"Error: {db_path} not found")
        return

    tokens = json.load(open(args.tokens))
    db = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()

    existing = {row[0] for row in db.execute("SELECT email FROM providerConnections WHERE provider='kiro'")}
    
    injected = 0
    skipped = 0
    
    for email, tok in tokens.items():
        if email in existing:
            print(f"  SKIP {email} (already exists)")
            skipped += 1
            continue
            
        expires = (datetime.now(timezone.utc) + timedelta(seconds=tok.get('expiresIn', 3600))).isoformat()
        data = json.dumps({
            'accessToken': tok.get('accessToken'),
            'refreshToken': tok.get('refreshToken', ''),
            'expiresAt': expires,
            'providerSpecificData': {
                'profileArn': tok.get('profileArn'),
                'authMethod': 'google',
                'provider': 'Google',
            },
            'testStatus': 'active',
        })
        
        db.execute(
            'INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (str(uuid.uuid4()), 'kiro', 'oauth', 'Kiro - Google', email, 1, 1, data, now, now)
        )
        print(f"  INJECTED {email}")
        injected += 1

    db.commit()
    db.close()
    print(f"\nDone: {injected} injected, {skipped} skipped")

if __name__ == "__main__":
    main()
