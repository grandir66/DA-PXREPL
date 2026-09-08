"""Impaginazione HTML delle mail di DAPX.

Le notifiche erano due cose brutte in modi diversi. La mail per singolo job
era un fascicolo lungo — intestazione, cluster, modulo, due riquadri, VM,
data, durata, dettagli — per dire una cosa sola: «la replica è andata». Il
riepilogo giornaliero era una tabella a sei colonne, che su un telefono si
accartoccia. In tutti e due i casi le cose fondamentali — che cosa, quando,
com'è finita — erano annegate («GUARDA QUANTO È LUNGO E COME È DIFFICILE
LEGGERE LE COSE FONDAMENTALI», 2026-09-08).

Qui sta il vestito: un'intestazione, un riquadro coi numeri, e per ogni
attività **una riga di intestazione col corpo sotto** — impilata, non
affiancata. Una colonna sola non si accartoccia.

Le regole d'obbligo, che spiegano perché il codice è così noioso, sono le
stesse che INTEGRA si è scritto in `app/mail_layout.py` (2026-08-26). Questa
è una **copia dichiarata**, non un modulo condiviso: repo separati, nessun
contratto comune. Se una delle due cambia, l'altra non la segue da sola — e
nemmeno la terza gemella, in DA-News.

* **Tabelle, non flex/grid.** Outlook impagina con Word: `display:flex`,
  `grid` e `float` non esistono. Quel che sta in riga sta in un `<td>`. Il
  vecchio riquadro sorgente/destinazione usava `display:grid`: in Outlook le
  due schede finivano una sotto l'altra a tutta larghezza.
* **Stili in linea, non `<style>`.** Gmail rimuove il foglio nel `<head>` in
  diverse configurazioni; una regola non applicata qui vuol dire testo nero
  su fondo nero, non un ritocco estetico mancato.
* **Nessuna immagine remota.** Barre e pastiglie sono celle colorate.
* **Colori a tinta piena**: il colore deve rispondere prima del testo.

Il testo semplice e il messaggio Telegram non sono un ripiego: dicono le
stesse cose. Chi aggiunge una sezione qui la aggiunge anche là.
"""

from __future__ import annotations

from html import escape
from typing import Any

# --- Tavolozza Domarc (valori fissi: in una mail non ci sono variabili CSS) ---
NAVY = "#0D2537"
INK = "#0D2537"
MUTED = "#4A6070"
LINE = "#D0D8DC"
SURFACE = "#ffffff"
SURFACE_2 = "#F5F7F9"
BG = "#EDEDED"

# Il cian puro (#00A7E7) è 2,7:1 sul bianco: fa bordi e riquadri, mai testo.
# Per le scritte cliccabili la variante scura, che passa il contrasto.
CIANO = "#00A7E7"
CIANO_SCURO = "#006C96"
ROSSO = "#D64545"
AMBRA = "#B58900"
VERDE = "#0EA371"

# Signika è il font del marchio, ma in posta non si può caricare: se chi legge
# ce l'ha installato la usa, altrimenti scende sulla pila di sistema.
FONT = "Signika,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif"


def esc(v: Any) -> str:
    """Testo pronto da mettere in HTML. `None` diventa stringa vuota, non «None»."""
    return escape("" if v is None else str(v), quote=True)


def url_valido(url: str | None) -> bool:
    """Solo http/https finiscono in un `href`.

    Le URL del digest vengono da feed esterni: senza questo controllo un
    `javascript:` o un `data:` diventerebbe un link cliccabile dentro una mail
    che porta il nostro nome.
    """
    u = (url or "").strip().lower()
    return u.startswith(("http://", "https://"))


def link(url: str | None, testo: str, *, colore: str = CIANO_SCURO) -> str:
    """Testo cliccabile, o solo testo se l'indirizzo manca o non è valido."""
    if not url_valido(url):
        return esc(testo)
    return (
        f'<a href="{esc(url)}" style="color:{colore};text-decoration:none;">{esc(testo)}</a>'
    )


def documento(*, titolo: str, occhiello: str, corpo: str, piede: str = "") -> str:
    """La busta: intestazione navy, corpo su fondo bianco, piede piccolo.

    `corpo` è già HTML (riquadri, sezioni): questa funzione non lo tocca.
    """
    piede_html = f'<div style="margin-top:6px;">{piede}</div>' if piede else ""
    return f"""<!DOCTYPE html>
<html lang="it"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{esc(titolo)}</title>
</head>
<body style="margin:0;padding:0;background:{BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{BG};padding:16px 8px;">
 <tr><td align="center">
  <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0"
         style="width:100%;max-width:640px;background:{SURFACE};
                border:1px solid {LINE};border-radius:10px;overflow:hidden;">
   <tr><td style="background:{NAVY};padding:18px 22px;">
     <div style="font:700 18px/1.25 {FONT};color:#ffffff;letter-spacing:-0.015em;">
       {esc(titolo)}</div>
     <div style="font:300 13px/1.45 {FONT};color:#B6C8D4;margin-top:4px;">
       {esc(occhiello)}</div>
   </td></tr>
   <tr><td style="padding:0 0 8px 0;">{corpo}</td></tr>
   <tr><td style="background:{SURFACE_2};border-top:1px solid {LINE};padding:14px 22px;
                  font:300 12px/1.5 {FONT};color:{MUTED};">
     DAPX — notifica automatica. Non si risponde a questo indirizzo.{piede_html}
   </td></tr>
  </table>
 </td></tr>
</table>
</body></html>
"""


def riquadro_numeri(voci: list[dict[str, Any]]) -> str:
    """La riga dei conti in cima: quanti, di che cosa, in che colore.

    Serve a decidere in due secondi se la mail va aperta adesso o dopo il
    caffè. Le voci a zero non si mostrano: un contatore a zero occupa spazio e
    non dice niente che non dica già la sua assenza.
    """
    vive = [v for v in voci if int(v.get("n") or 0) > 0]
    if not vive:
        return ""
    larghezza = f"{100 // len(vive)}%"
    celle = []
    for v in vive:
        colore = str(v.get("colore") or NAVY)
        # `testo` sostituisce il numero quando il valore non è un conteggio
        # (una durata, per esempio): `n` continua a decidere se la voce si
        # mostra, così la regola dello zero vale anche lì.
        valore = str(v.get("testo") or v.get("n"))
        misura = 26 if len(valore) <= 4 else 20
        dentro = (
            f'<div style="font:700 {misura}px/1.15 {FONT};color:#ffffff;">{esc(valore)}</div>'
            f'<div style="font:600 10px/1.3 {FONT};color:#ffffff;margin-top:5px;'
            f'text-transform:uppercase;letter-spacing:.4px;">{esc(v.get("etichetta"))}</div>'
        )
        celle.append(
            f'<td width="{larghezza}" align="center" valign="top" style="padding:4px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td align="center" style="background:{colore};border-radius:8px;'
            f'padding:12px 4px;" bgcolor="{colore}">{dentro}</td></tr></table></td>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="padding:16px 14px 6px 14px;"><tr>{"".join(celle)}</tr></table>'
    )


def badge(testo: str, colore: str) -> str:
    """Etichetta a tinta piena (CVSS 9.8, AI, …): il colore risponde prima del testo."""
    return (
        f'<span style="display:inline-block;background:{colore};color:#ffffff;'
        f"font:700 10px/1.4 {FONT};padding:3px 7px;border-radius:4px;"
        f'text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;">'
        f"{esc(testo)}</span>"
    )


# --- gli stati, e come si vedono ------------------------------------------
#
# Il colore risponde prima del testo, ma da solo non basta: su un monitor mal
# calibrato o per chi non distingue rosso e verde sparisce. Quindi doppio
# segnale — colore E parola. I successi però restano muti: se ogni riga porta
# una pastiglia verde, la pastiglia rossa non si vede più. Un'attività andata
# bene si riconosce dal fatto che non ha niente da dire.

STATI = {
    "success": ("", VERDE),
    "failed": ("Fallito", ROSSO),
    "warning": ("Attenzione", AMBRA),
    # Pianificato ma fermo. Non è «mai eseguito»: può aver funzionato per mesi
    # e aver smesso ieri, ed è il caso peggiore perché non alza nessun errore.
    "fermo": ("Non partito", AMBRA),
    # Fallito e rimesso a posto dalla riprova automatica: il sistema si è
    # aggiustato da solo. Ciano scuro, non ambra: non c'è niente da fare.
    "riprovato": ("Riuscita alla riprova", CIANO_SCURO),
    "running": ("In corso", CIANO_SCURO),
    "never_run": ("Mai eseguito", MUTED),
}


def colore_stato(stato: str) -> str:
    return STATI.get(stato, ("", MUTED))[1]


def attivita(
    *,
    stato: str,
    oggetto: str,
    quando: str = "",
    durata: str = "",
    percorso: str = "",
    dettagli: list[str] | None = None,
    errore: str = "",
    sistema: str = "",
    ultima: bool = False,
) -> str:
    """Un'attività: intestazione sopra, dettagli sotto. Mai in colonne.

    L'intestazione porta le cose per cui si apre la mail — che cosa, quando,
    quanto è durato, da dove a dove. I dettagli (byte trasferiti, dataset,
    errore) stanno sotto, dove non rubano spazio a quelle.
    """
    parola, colore = STATI.get(stato, ("", MUTED))
    etichette = []
    if parola:
        etichette.append(badge(parola, colore))
    if sistema:
        etichette.append(badge(sistema, NAVY))

    testa = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td valign="middle" style="font:700 14px/1.4 {FONT};color:{INK};'
        f'letter-spacing:-0.015em;">{esc(oggetto)}</td>'
        f'<td valign="middle" align="right" style="white-space:nowrap;padding-left:8px;">'
        f'{" ".join(etichette)}</td></tr></table>'
    )

    contorno = " · ".join(x for x in (quando, durata, percorso) if x)
    contorno_html = (
        f'<div style="font:400 12px/1.5 {FONT};color:{MUTED};margin-top:3px;">'
        f"{esc(contorno)}</div>"
        if contorno
        else ""
    )

    righe = "".join(
        f'<div style="font:400 12px/1.5 {FONT};color:{MUTED};margin-top:2px;'
        f'word-break:break-all;">{esc(d)}</div>'
        for d in (dettagli or [])
        if d
    )

    errore_html = ""
    if errore:
        errore_html = (
            f'<div style="margin-top:6px;background:#FBEAEA;border-left:3px solid {ROSSO};'
            f"border-radius:0 4px 4px 0;padding:7px 9px;font:400 12px/1.45 {FONT};"
            f'color:{INK};word-break:break-word;">{esc(errore)}</div>'
        )

    bordo = "" if ultima else f"border-bottom:1px solid {LINE};"
    return (
        f'<tr><td style="padding:11px 0 12px 0;{bordo}">'
        f"{testa}{contorno_html}{righe}{errore_html}</td></tr>"
    )


def sezione(
    *,
    titolo: str,
    sottotitolo: str,
    colore: str,
    voci: list[str],
    vuoto: str,
    conta: bool = True,
) -> str:
    """Un blocco per tipologia: barra colorata, titolo col conto, attività impilate.

    La barra è rossa se dentro c'è un fallimento: si trova la tipologia col
    problema scorrendo il margine, senza leggere una parola.
    """
    if voci:
        dentro = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0">{"".join(voci)}</table>'
        )
    else:
        dentro = (
            f'<div style="font:300 13px/1.5 {FONT};color:{MUTED};margin-top:10px;">'
            f"{esc(vuoto)}</div>"
        )
    conta_html = (
        f'<span style="color:{colore};">({len(voci)})</span>' if conta and voci else ""
    )
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="padding:14px 18px 4px 18px;">
 <tr>
  <td width="5" style="background:{colore};border-radius:3px;" bgcolor="{colore}">&nbsp;</td>
  <td style="padding-left:12px;">
    <div style="font:700 15px/1.3 {FONT};color:{INK};letter-spacing:-0.015em;">{esc(titolo)}
      {conta_html}</div>
    <div style="font:300 12px/1.4 {FONT};color:{MUTED};margin-top:2px;">{esc(sottotitolo)}</div>
    {dentro}
  </td>
 </tr>
</table>
"""


def nota_tecnica(titolo: str, testo: str, *, massimo: int = 1500) -> str:
    """L'output grezzo di un comando, in coda e in piccolo.

    Serve a chi indaga su un guasto, non a chi legge l'esito: se sta in mezzo
    alla pagina si porta via l'attenzione dalle cose che contano. Tagliato,
    perché un `rsync -v` che ha copiato diecimila file riempirebbe la casella
    di posta di chi lo riceve.
    """
    corpo = (testo or "").strip()
    if not corpo:
        return ""
    if len(corpo) > massimo:
        corpo = corpo[:massimo] + f"\n… (altri {len(testo.strip()) - massimo} caratteri)"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="padding:6px 18px 14px 18px;"><tr><td>'
        f'<div style="font:600 11px/1.4 {FONT};color:{MUTED};text-transform:uppercase;'
        f'letter-spacing:.4px;margin-bottom:5px;">{esc(titolo)}</div>'
        f'<div style="background:{SURFACE_2};border:1px solid {LINE};border-radius:6px;'
        f"padding:9px 11px;font:400 11px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f'color:{INK};white-space:pre-wrap;word-break:break-word;">{esc(corpo)}</div>'
        f"</td></tr></table>"
    )
