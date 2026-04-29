"""Chan doan cau hinh Google Cloud cho VIC OCR.

Chay: ``venv\\Scripts\\python.exe scripts\\verify_gcp.py [<user_id>]``
(mac dinh user_id=1, tuc admin)

Kiem tra:
1. Service Account JSON ton tai va doc duoc
2. Project ID trong JSON co khop voi config khong
3. Document AI API co bat khong
4. Service Account co quyen Document AI API User khong
5. Processor co ton tai khong
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.models import UserOCRConfig


def main() -> int:
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    app = create_app()
    with app.app_context():
        config = UserOCRConfig.query.filter_by(user_id=user_id).first()
        if config is None:
            print(f"[X] Khong tim thay UserOCRConfig cho user_id={user_id}")
            return 1

        print(f"=== Verify GCP config for user_id={user_id} ===\n")
        print(f"Project ID:    {config.documentai_project_id or '(empty)'}")
        print(f"Location:      {config.documentai_location or '(empty)'}")
        print(f"Processor ID:  {config.documentai_processor_id or '(empty)'}")
        print(f"Credentials:   {config.google_credentials_path or '(empty)'}\n")

        # 1. Check JSON file (per-user config first, then env fallback)
        cred_path = config.google_credentials_path or ""
        if not cred_path or not Path(cred_path).exists():
            fallback = app.config.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if fallback and Path(fallback).exists():
                print(f"[!]  Per-user credentials trong (su dung fallback tu .env)")
                cred_path = fallback
            else:
                print(f"[X] BUOC 1: Khong tim thay JSON credentials")
                print(f"     Per-user:  {config.google_credentials_path or '(empty)'}")
                print(f"     Fallback:  {fallback or '(empty)'}")
                return 1
        try:
            with open(cred_path, "r", encoding="utf-8") as fh:
                cred = json.load(fh)
        except Exception as exc:
            print(f"[X] BUOC 1: Khong parse duoc JSON: {exc}")
            return 1
        sa_email = cred.get("client_email", "?")
        json_project = cred.get("project_id", "?")
        print(f"[OK] BUOC 1: Service Account JSON parsed")
        print(f"     - client_email: {sa_email}")
        print(f"     - project_id (trong JSON): {json_project}")

        # 2. Compare project IDs
        ui_project = config.documentai_project_id
        if ui_project and json_project != ui_project:
            print()
            print(f"[!]  BUOC 2: CANH BAO - Project ID khong khop!")
            print(f"     Trong JSON:   {json_project}")
            print(f"     Trong VIC OCR: {ui_project}")
            print(f"     -> Hau het truong hop ban can dung Project ID tu JSON: {json_project}")
        else:
            print(f"[OK] BUOC 2: Project ID khop ({json_project})")

        # 3. Try Document AI client
        target_project = ui_project or json_project
        location = config.documentai_location or "us"
        processor_id = config.documentai_processor_id

        if not processor_id:
            print(f"[X] BUOC 3: Chua nhap Processor ID")
            return 1

        try:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai
            opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
            client = documentai.DocumentProcessorServiceClient(client_options=opts)

            full_name = f"projects/{target_project}/locations/{location}/processors/{processor_id}"
            print(f"\n[..] BUOC 3: Test get_processor({full_name})")
            proc = client.get_processor(name=full_name)
            print(f"[OK] BUOC 3: Processor ton tai!")
            print(f"     - Display name: {proc.display_name}")
            print(f"     - Type:         {proc.type_}")
            print(f"     - State:        {proc.state.name}")
        except Exception as exc:
            err = str(exc)
            print(f"[X] BUOC 3: {err[:300]}")
            print()
            print("=== HUONG DAN SUA ===")
            if "CONSUMER_INVALID" in err or "Permission denied on resource project" in err:
                print(f"Project '{target_project}' khong hop le. Kiem tra:")
                print(f"  1. Project ID dung khong? (Project NAME != Project ID)")
                print(f"     Vao https://console.cloud.google.com -> bam vao project name")
                print(f"     o thanh tren -> tab 'IAM & Admin' -> 'Settings' -> xem 'Project ID'")
                print(f"  2. Da bat Document AI API chua?")
                print(f"     https://console.cloud.google.com/apis/library/documentai.googleapis.com")
                print(f"  3. Project da link voi Billing chua?")
                print(f"     https://console.cloud.google.com/billing")
            elif "PERMISSION_DENIED" in err:
                print(f"Service Account thieu role. Cap phat them:")
                print(f"  IAM & Admin -> IAM -> tim {sa_email} -> Edit -> Add role:")
                print(f"  'Document AI API User'")
            elif "NOT_FOUND" in err:
                print(f"Processor ID khong ton tai trong project/location nay.")
                print(f"  Vao Document AI -> Processors -> kiem tra ID + region")
            return 1

        print(f"\n=== TAT CA KIEM TRA PASS ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
