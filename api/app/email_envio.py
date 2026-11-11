"""Envio de e-mail do PavimentAI.

Este arquivo fica na MESMA pasta do config.py, do deps.py e do schemas.py.

- Se SMTP_HOST NÃO estiver no .env, esta função não faz nada (o código continua
  aparecendo no terminal da API quando AMBIENTE=dev, como já acontece hoje).
- Se SMTP_HOST estiver no .env, o e-mail é enviado de verdade.
- Nunca levanta erro: se o envio falhar, só registra no log da API.
"""
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("pavimentai.email")


def enviar_email(destino: str, assunto: str, texto: str) -> None:
    if not settings.smtp_host:
        if settings.ambiente != "dev":
            log.warning("SMTP não configurado: o e-mail para %s não foi enviado.", destino)
        return

    try:
        if not settings.smtp_usuario or not settings.smtp_senha:
            raise RuntimeError("Defina SMTP_USUARIO e SMTP_SENHA no .env (junto com SMTP_HOST).")

        msg = EmailMessage()
        msg["From"] = settings.smtp_remetente or settings.smtp_usuario
        msg["To"] = destino
        msg["Subject"] = assunto
        msg.set_content(texto)

        if settings.smtp_porta == 465:  # conexão já criptografada desde o início
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_porta, timeout=15) as smtp:
                smtp.login(settings.smtp_usuario, settings.smtp_senha)
                smtp.send_message(msg)
        else:  # porta 587: começa simples e liga a criptografia
            with smtplib.SMTP(settings.smtp_host, settings.smtp_porta, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(settings.smtp_usuario, settings.smtp_senha)
                smtp.send_message(msg)
    except Exception:
        log.exception("Falha ao enviar e-mail para %s", destino)
        
