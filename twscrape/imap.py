import asyncio
import email as emaillib
import imaplib
import os
import time
from datetime import datetime, timezone

from .logger import logger

TWS_WAIT_EMAIL_CODE = [os.getenv("TWS_WAIT_EMAIL_CODE"), os.getenv("LOGIN_CODE_TIMEOUT"), 60]
TWS_WAIT_EMAIL_CODE = [int(x) for x in TWS_WAIT_EMAIL_CODE if x is not None][0]


class EmailLoginError(Exception):
    def __init__(self, message="Email login error"):
        self.message = message
        super().__init__(self.message)


class EmailCodeTimeoutError(Exception):
    def __init__(self, message="Email code timeout"):
        self.message = message
        super().__init__(self.message)


IMAP_MAPPING: dict[str, str] = {
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
}


def add_imap_mapping(email_domain: str, imap_domain: str):
    IMAP_MAPPING[email_domain] = imap_domain


def _get_imap_domain(email: str) -> str:
    email_domain = email.split("@")[1]
    if email_domain in IMAP_MAPPING:
        return IMAP_MAPPING[email_domain]
    return f"imap.{email_domain}"


def _wait_email_code(imap: imaplib.IMAP4_SSL, count: int, min_t: datetime | None) -> str | None:
    for i in range(count, 0, -1):
        _, rep = imap.fetch(str(i), "(RFC822)")
        for x in rep:
            if isinstance(x, tuple):
                msg = emaillib.message_from_bytes(x[1])

                try:
                    msg_time = datetime.strptime(msg.get("Date", "").split(' (')[0], "%a, %d %b %Y %H:%M:%S %z")
                    msg_time = msg_time.astimezone(timezone.utc)

                except ValueError:
                    try:
                        msg_time = datetime.strptime(msg.get("Date", "").split(' (')[0], "%a, %d %b %Y %H:%M:%S %Z")
                        msg_time = msg_time.astimezone(timezone.utc)

                    except:    
                        msg_time = msg.get("Date", "")

                print("MSGTİME", msg_time)

                msg_from = str(msg.get("From", "")).lower()
                msg_subj = str(msg.get("Subject", "")).lower()
                logger.info(f"({i} of {count}) {msg_from} - {msg_time} - {msg_subj}")

                if min_t is not None and msg_time < min_t:
                    return None

                if "info@x.com" in msg_from and "confirmation code is" in msg_subj:
                    # eg. Your Twitter confirmation code is XXX
                    return msg_subj.split(" ")[-1].strip()

    return None


async def imap_get_email_code(
    imap: imaplib.IMAP4_SSL, email: str, min_t: datetime | None = None
) -> str:
    try:
        logger.info(f"Waiting for confirmation code for {email}...")
        overall_start_time = time.time()

        folders_to_check = ['Spam', 'INBOX']
        for folder in folders_to_check:
            try:
                imap.select(f'{folder}', readonly=True)
            except Exception as e:
                logger.error(f"Error selecting folder {folder}: {e}")
                print(f"Error selecting folder {folder}: {e}")
                continue  # Eğer klasör seçilemezse diğer klasöre geç

            start_time = time.time()  # Her klasör için kontrol başlangıcında zamanı kaydet
            while True:
                _, rep = imap.search(None, 'ALL')
                msg_numbers = rep[0].split()
                code = _wait_email_code(imap, len(msg_numbers), min_t)
                if code is not None:
                    return code

                elapsed_time = time.time() - start_time
                overall_elapsed_time = time.time() - overall_start_time
                if elapsed_time > TWS_WAIT_EMAIL_CODE or overall_elapsed_time > TWS_WAIT_EMAIL_CODE:
                    raise EmailCodeTimeoutError(f"Email code timeout ({TWS_WAIT_EMAIL_CODE} sec)")

                await asyncio.sleep(3)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        print(f"An error occurred: {e}")
        imap.close()
        raise e


async def imap_login(email: str, password: str):
    domain = _get_imap_domain(email)
    imap = imaplib.IMAP4_SSL(domain)

    try:
        imap.login(email, password)
        imap.select("INBOX", readonly=True)
    except imaplib.IMAP4.error as e:
        logger.error(f"Error logging into {email} on {domain}: {e}")
        raise EmailLoginError() from e

    return imap
