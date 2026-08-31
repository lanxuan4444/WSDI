"""Generate a B2 signed download URL for any file in the bucket."""
import sys
sys.path.insert(0, r'D:\WSDI\server')
import b2

# File path in B2 bucket (relative to bucket root)
file_path = sys.argv[1] if len(sys.argv) > 1 else 'pe/AHPE_1.0.iso'

print(f"Generating signed URL for: {file_path}")
url = b2.get_signed_download_url(file_path)
if url:
    print(f"\nSigned URL (valid 7 days):")
    print(url)
    print(f"\nOpen this URL in browser to download.")
else:
    print("Failed to generate signed URL")
