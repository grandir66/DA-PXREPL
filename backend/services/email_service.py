"""
Email Service - Invio notifiche via email
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Servizio per invio email SMTP"""
    
    def __init__(self):
        self.host: Optional[str] = None
        self.port: int = 587
        self.user: Optional[str] = None
        self.password: Optional[str] = None
        self.from_addr: Optional[str] = None
        self.to_addrs: List[str] = []
        self.subject_prefix: str = "[DAPX]"
        self.use_tls: bool = True
    
    def configure(
        self,
        host: str,
        port: int = 587,
        user: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addrs: Optional[str] = None,
        subject_prefix: str = "[DAPX]",
        use_tls: bool = True
    ):
        """Configura il servizio email"""
        # strip: uno spazio incollato nell'host produce "[Errno -2] Name or service
        # not known" in getaddrinfo — sanitizzare qui copre ogni chiamante.
        self.host = (host or "").strip()
        self.port = port
        self.user = (user or "").strip() or None
        self.password = password
        self.from_addr = ((from_addr or "").strip() or None) or self.user
        self.to_addrs = [addr.strip() for addr in (to_addrs or "").split(",") if addr.strip()]
        self.subject_prefix = subject_prefix
        self.use_tls = use_tls
    
    def send_email(
        self,
        subject: str,
        body: str,
        to_addrs: Optional[List[str]] = None,
        html: bool = False,
        text_body: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Invia un'email.
        
        Args:
            subject: Oggetto dell'email
            body: Corpo dell'email
            to_addrs: Lista destinatari (opzionale, usa default se non specificato)
            html: Se True, invia come HTML
            
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        if not self.host:
            return False, "Server SMTP non configurato"
        
        recipients = to_addrs or self.to_addrs
        if not recipients:
            return False, "Nessun destinatario configurato"
        
        if not self.from_addr:
            return False, "Mittente non configurato"
        
        try:
            # Prepara il messaggio
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"{self.subject_prefix} {subject}"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(recipients)
            msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
            
            # Aggiungi corpo. In `multipart/alternative` l'ordine conta: il
            # testo semplice PRIMA, l'HTML dopo — chi legge sceglie l'ultima
            # parte che sa mostrare. Invertirli fa vedere il testo grezzo a
            # tutti. Chi legge da orologio, da lettore di schermo o
            # dall'archivio deve trovare le stesse cose dell'HTML.
            if html and text_body:
                msg.attach(MIMEText(text_body, "plain", "utf-8"))
            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type, "utf-8"))
            
            # Connessione SMTP
            if self.port == 465:
                # SSL diretto (porta 465)
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, context=context) as server:
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.sendmail(self.from_addr, recipients, msg.as_string())
            elif self.use_tls:
                # STARTTLS (porta 587)
                context = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    server.starttls(context=context)
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.sendmail(self.from_addr, recipients, msg.as_string())
            else:
                # Nessuna cifratura (porta 25 o altre)
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.sendmail(self.from_addr, recipients, msg.as_string())
            
            logger.info(f"Email inviata a {recipients}: {subject}")
            return True, "Email inviata con successo"
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Errore autenticazione SMTP: {e}")
            return False, f"Errore autenticazione: {str(e)}"
        except smtplib.SMTPException as e:
            logger.error(f"Errore SMTP: {e}")
            return False, f"Errore SMTP: {str(e)}"
        except Exception as e:
            logger.error(f"Errore invio email: {e}")
            return False, f"Errore: {str(e)}"
    
    def send_job_notification(
        self,
        job_name: str,
        status: str,  # success, failed, warning
        source: str,
        destination: str,
        duration: Optional[int] = None,
        error: Optional[str] = None,
        details: Optional[str] = None,
        cluster_name: Optional[str] = None,
        source_node_name: Optional[str] = None,
        dest_node_name: Optional[str] = None,
        job_type: Optional[str] = None,  # sync, backup, recovery, migration
        vm_name: Optional[str] = None,
        vm_id: Optional[int] = None,
        transferred: Optional[str] = None,
        notify_subject: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Notifica per una singola esecuzione (modalità `always` e `failure`).

        Era un fascicolo: intestazione, cluster, modulo ripetuto due volte,
        due riquadri affiancati con `display:grid` (che in Outlook non
        esiste), VM, data, durata, dettagli — tutto per dire una cosa sola.
        Adesso è una scheda: intestazione con quel che serve, dettagli sotto.
        Con l'impostazione predefinita dei job questa mail non parte affatto:
        l'attività finisce nel riepilogo giornaliero.
        """
        from services import mail_layout as ml
        from services import notification_summary as riepilogo

        tipologia = riepilogo.tipologia(job_type)
        parola_stato = {
            "success": "completata",
            "failed": "FALLITA",
            "warning": "con avvisi",
        }.get(status, status)

        # L'oggetto: la cosa replicata, non il nome del job. Il nome lo ha
        # scelto chi ha creato il job e spesso non dice niente a chi legge.
        if vm_name and vm_id:
            oggetto = f"{vm_name} ({vm_id})"
        elif vm_name:
            oggetto = vm_name
        elif vm_id:
            oggetto = f"VM {vm_id}"
        else:
            oggetto = job_name

        percorso = ""
        if source_node_name and dest_node_name:
            percorso = f"{source_node_name} → {dest_node_name}"
        elif source_node_name:
            percorso = source_node_name

        dettagli = []
        if transferred:
            dettagli.append(f"trasferiti {transferred}")
        if source or destination:
            dettagli.append(f"{source or '—'} → {destination or '—'}")

        quando = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M %Z").strip()

        # Ogni informazione una volta sola. Prima l'oggetto della replica
        # compariva tre volte (titolo, riquadro, badge) e il modulo due: la
        # mail sembrava lunga senza dire niente di più.
        corpo = ml.sezione(
            titolo=f"{tipologia.sigla} · {tipologia.descrizione}",
            sottotitolo="",
            colore=ml.colore_stato(status),
            conta=False,
            voci=[
                ml.attivita(
                    stato=status,
                    oggetto=job_name,
                    quando=quando,
                    durata=riepilogo.durata_breve(duration),
                    percorso=percorso,
                    dettagli=dettagli,
                    errore=error or "",
                    ultima=True,
                )
            ],
            vuoto="",
        )
        # L'output del comando serve a chi indaga, non a chi legge l'esito:
        # sta in fondo, in piccolo, e non toglie spazio alle cose importanti.
        if details:
            corpo += ml.nota_tecnica("Dettagli", details)

        html = ml.documento(
            titolo=f"{parola_stato.capitalize()}: {oggetto}",
            occhiello=" · ".join(x for x in (cluster_name, quando) if x),
            corpo=corpo,
            piede="",
        )

        testo_semplice = "\n".join(
            x
            for x in (
                f"{parola_stato.capitalize()}: {oggetto}",
                f"{tipologia.sigla} · {job_name}",
                f"{quando} · {riepilogo.durata_breve(duration) or 'durata n/d'}",
                percorso,
                *dettagli,
                f"Errore: {error}" if error else "",
            )
            if x
        )

        emoji = {"success": "✅", "failed": "❌", "warning": "⚠️"}.get(status, "ℹ️")
        subject = (
            notify_subject.strip()
            if notify_subject and notify_subject.strip()
            else f"{emoji} {tipologia.sigla} {parola_stato}: {oggetto}"
        )

        return self.send_email(subject, html, html=True, text_body=testo_semplice)

    def send_test_email(self) -> Tuple[bool, str]:
        """Mail di prova. Porta la stessa veste delle altre: chi configura
        l'SMTP vede subito che aspetto avranno davvero le notifiche."""
        from services import mail_layout as ml

        quando = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M %Z").strip()
        corpo = ml.sezione(
            titolo="Prova riuscita",
            sottotitolo="la configurazione SMTP funziona",
            colore=ml.VERDE,
            voci=[
                ml.attivita(
                    stato="success",
                    oggetto="Invio di prova",
                    quando=quando,
                    percorso=f"{self.host}:{self.port}",
                    dettagli=[f"mittente {self.from_addr}"],
                    ultima=True,
                )
            ],
            vuoto="",
        )
        html = ml.documento(
            titolo="Prova notifiche DAPX",
            occhiello=quando,
            corpo=corpo,
            piede="Se leggi questo messaggio, le notifiche possono partire.",
        )
        testo = (
            f"Prova notifiche DAPX — riuscita\n{quando}\n"
            f"Server {self.host}:{self.port} · mittente {self.from_addr}"
        )
        return self.send_email("🧪 Prova notifiche", html, html=True, text_body=testo)

# Istanza singleton
email_service = EmailService()


