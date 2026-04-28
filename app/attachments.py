"""
Attachment handling and text extraction.
"""
import os
import urllib.request
from agentmail import AgentMail
from .database import ApplicantFile
from .config import AGENTMAIL_API_KEY, RESUME_DIR, COVER_LETTER_DIR, OTHER_DIR

# Initialize AgentMail client
agentmail_client = AgentMail(api_key=AGENTMAIL_API_KEY)


def extract_text_from_file(file_path: str, filename: str) -> str:
    """Extract text from PDF and text files."""
    try:
        lower_filename = filename.lower()
        
        # PDF extraction
        if lower_filename.endswith('.pdf'):
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    return text.strip()[:10000]  # Limit to 10k chars
            except ImportError:
                print(f"  ⚠️ PyPDF2 not installed, skipping PDF text extraction")
                return ""
            except Exception as e:
                print(f"  ⚠️ Failed to extract PDF text: {e}")
                return ""
        
        # Text file extraction
        elif lower_filename.endswith(('.txt', '.md', '.csv')):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()[:10000]
            except Exception as e:
                print(f"  ⚠️ Failed to extract text: {e}")
                return ""
        
        return ""
    except Exception as e:
        print(f"  ⚠️ Text extraction error: {e}")
        return ""


def attachment_handler(attachments, thread_id, sender, inbox_id, message_id, db):
    """Process and save attachments, extracting text where possible."""
    saved_files = {}
    extracted_texts = {}
    
    for attachment in attachments:
        original_filename = attachment.get("filename")
        attachment_id = attachment.get("attachment_id")
        if not original_filename or not attachment_id:
            continue
        
        lower_filename = original_filename.lower()
        if any(kw in lower_filename for kw in ["resume", "cv"]):
            file_type, save_dir = "resume", RESUME_DIR
        elif "cover" in lower_filename:
            file_type, save_dir = "cover_letter", COVER_LETTER_DIR
        else:
            file_type, save_dir = "other", OTHER_DIR
        
        stored_filename = f"{thread_id}_{attachment_id}_{original_filename}"
        file_path = os.path.join(save_dir, stored_filename)
        saved_files[file_type] = file_path
        
        try:
            attachment_response = agentmail_client.inboxes.messages.get_attachment(
                inbox_id=inbox_id, message_id=message_id, attachment_id=attachment_id,
            )
            download_url = getattr(attachment_response, "download_url", None)
            if not download_url and isinstance(attachment_response, dict):
                download_url = attachment_response.get("download_url")
            
            if download_url:
                with urllib.request.urlopen(download_url) as response:
                    file_bytes = response.read()
                with open(file_path, "wb") as f:
                    f.write(file_bytes)
                
                # Extract text from the file
                extracted_text = extract_text_from_file(file_path, original_filename)
                if extracted_text:
                    extracted_texts[file_type] = extracted_text
                    print(f"  📄 Extracted {len(extracted_text)} chars from {original_filename}")
                
                db.add(ApplicantFile(
                    thread_id=thread_id, candidate_email=sender, message_id=message_id,
                    file_type=file_type, original_filename=original_filename,
                    stored_filename=stored_filename, file_path=file_path,
                ))
        except Exception as e:
            print(f"  ⚠️ Failed to save attachment {original_filename}: {e}")
    
    return saved_files, extracted_texts
