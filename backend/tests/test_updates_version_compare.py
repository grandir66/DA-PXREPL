"""
Test invariante: "aggiornamento disponibile" solo se la versione pubblicata
e' PIU' NUOVA di quella installata.

Incidente 2026-09-08 (DA-PXREPL in esercizio, v3.21.0): il confronto era
`current != available`, cioe' "diverso" invece di "piu' nuovo". Il commit di
release 3.21.0 era stato pushato senza tag ne' GitHub Release, quindi
`releases/latest` rispondeva 3.20.16 e la pagina "Aggiornamenti Sistema"
mostrava il badge verde "Aggiornamento disponibile!" verso una versione
PRECEDENTE a quella installata. La stessa riga accendeva il badge anche
quando GitHub rispondeva "rate_limit" al posto di una versione.
"""

import pytest

from routers.updates import confronta_versioni, parse_version


class TestParseVersion:
    def test_semver_semplice(self):
        assert parse_version("3.21.0") == (3, 21, 0)

    def test_prefisso_v_e_suffissi(self):
        assert parse_version("v3.21.0") == (3, 21, 0)
        assert parse_version("3.21.0-rc1") == (3, 21, 0)

    def test_non_versioni(self):
        for valore in ("", None, "unknown", "rate_limit", "35cbffc"):
            assert parse_version(valore) is None


class TestConfrontaVersioni:
    def test_pubblicata_piu_nuova_e_un_aggiornamento(self):
        assert confronta_versioni("3.20.16", "3.21.0") == (True, False)

    def test_installata_piu_nuova_non_e_un_aggiornamento(self):
        """L'incidente: 3.21.0 installata, 3.20.16 pubblicata."""
        assert confronta_versioni("3.21.0", "3.20.16") == (False, True)

    def test_stessa_versione(self):
        assert confronta_versioni("3.21.0", "3.21.0") == (False, False)

    def test_confronto_numerico_non_lessicografico(self):
        """3.20.9 < 3.20.16: come stringhe l'ordine sarebbe rovesciato."""
        assert confronta_versioni("3.20.9", "3.20.16") == (True, False)
        assert confronta_versioni("3.20.16", "3.20.9") == (False, True)

    def test_tag_con_prefisso_v(self):
        assert confronta_versioni("3.21.0", "v3.21.0") == (False, False)

    @pytest.mark.parametrize("available", ["", "unknown", "rate_limit"])
    def test_errori_github_non_sono_aggiornamenti(self, available):
        assert confronta_versioni("3.21.0", available) == (False, False)

    def test_versione_locale_ignota_non_accende_il_badge(self):
        assert confronta_versioni("unknown", "3.21.0") == (False, False)

    def test_installazione_da_commit_confronta_hash(self):
        """Repo senza tag: si puo' solo dire 'diverso', non 'piu' nuovo'."""
        assert confronta_versioni("35cbffc", "ef02b0a1234") == (True, False)
        assert confronta_versioni("35cbffc", "35cbffc890a") == (False, False)
