#!/usr/bin/env python3
"""SessionStart hook — injects a historical "on this day" anecdote.

Strategy:
  1. Occasionally (GALICIA_CHANCE) inject a curated Galician-culture anecdote
     instead of the day's event, so the user's region shows up now and then.
  2. Otherwise query Wikipedia's public "On This Day" API, biasing selection
     toward cultural events (film/music/art/literature) over war/politics.
  3. If the network fails, fall back to a small offline table (FALLBACK_ES).
  4. Emit the result via hookSpecificOutput.additionalContext as a directive
     telling Claude to open its first reply with the greeting + the anecdote.

All user-facing text is Spanish; code comments are English. The hook exits
silently (exit 0, no output) on any error so it never degrades session start.
"""

import json
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Personality greetings. One is picked at random and used as the opener
# BEFORE the anecdote. Copied verbatim by Claude (typos/memes intentional).
GREETINGS = [
    "¿Qué día tan bueno hoy para hacer combobulating no? Pero antes un poquito de historia…",
    "Cuánto tiempo sin verte, bro. Eres un máquina, literal. Pero antes un poquito de historia…",
    "Buenas as as as. ¿Sabes aquello de no te acostarás sin saber una cosa más? Pues estoy aquí a tu servicio…",
    "Para subir un poco de aur y alcanzar tu primer, te dejo una efémeride aesthetic. Ahí te va...",
    "Sé que sabes que es wingardium leviosa y no leviosá. Pero a que no sabes qué...",
    "Sé que sabes que es nucelar y no nuclear. Pero a que no sabes qué...",
    "¿A quien no le va a gustar una efémeride para iniciar sesión? Vamos allá...",
]

WIKIPEDIA_URL = (
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/all/{month:02d}/{day:02d}"
)
HTTP_TIMEOUT_SECS = 3
USER_AGENT = "okppg-on-this-day/0.1 (Claude Code plugin; +https://github.com/pablopenawet/claude_marketplace)"

# Cultural bias: prefer film/music/art/literature events over war/death/
# politics. Substring match against the English text the API returns. Not an
# exclusion — only a priority.
CULTURAL_KEYWORDS = (
    # cinema
    "film", "movie", "cinema", "premiere", "premiered", "box office",
    "blockbuster", "animated", "documentary", "screenplay",
    # music
    "album", "song", "single", "band", "orchestra", "symphony", "opera",
    "concert", "jazz", "rock", "hip hop", "recorded", "chart", "melody",
    "composer", "songwriter", "musician", "singer",
    # performing / visual arts
    "theatre", "theater", "ballet", "broadway", "painting", "sculpture",
    "exhibition", "museum", "painter", "artist",
    # literature
    "novel", "poem", "poet", "published", "book", "comic", "novelist",
    "playwright", "author", "writer",
    # awards / show business
    "oscar", "academy award", "grammy", "emmy", "cannes",
    "nobel prize in literature", "pulitzer", "actor", "actress", "director",
    # other cultural
    "television series", "sitcom", "video game",
)

# Probability that a session shows a Galician anecdote instead of the day's
# event. ~0.06 ≈ a couple of times a month at roughly one session per day.
# Tune freely.
GALICIA_CHANCE = 0.06

# Curated Galician anecdotes (Spanish, date-independent). Picked at random
# when the Galicia roll hits. Culture, history and geography — never grim.
GALICIA_EFEMERIDES = [
    # culture
    "1837 — Nace en Santiago de Compostela Rosalía de Castro, voz mayor de la poesía gallega y del Rexurdimento.",
    "1863 — Rosalía de Castro publica «Cantares Gallegos», obra fundacional de la literatura moderna en gallego.",
    "1188 — El Mestre Mateo remata el Pórtico da Gloria de la Catedral de Santiago, cumbre del románico europeo.",
    "1851 — Nace en A Coruña Emilia Pardo Bazán, introductora del naturalismo en la literatura española.",
    "1866 — Nace en Vilanova de Arousa Ramón María del Valle-Inclán, padre del esperpento.",
    "1916 — Se funda en A Coruña la primera Irmandade da Fala, germen del galleguismo cultural moderno.",
    "1944 — Castelao publica en el exilio «Sempre en Galiza», texto clave del pensamiento galleguista.",
    "1969 — Andrés do Barro triunfa con «O tren», una de las primeras canciones en gallego en las listas españolas.",
    "1979 — Nace en Santiago el grupo Milladoiro, referente de la música folk gallega.",
    "1989 — Camilo José Cela, nacido en Iria Flavia (Padrón), recibe el Premio Nobel de Literatura.",
    "1996 — Carlos Núñez publica «A Irmandade das Estrelas», llevando la gaita gallega a escenarios de todo el mundo.",
    "1998 — Manuel Rivas publica «O lapis do carpinteiro», éxito de la narrativa gallega contemporánea.",
    # history
    "813 — Según la tradición, se halla en Compostela el sepulcro del apóstol Santiago, origen del Camino de peregrinación.",
    "910 — García I es proclamado rey de Galicia, que llega a constituirse como reino propio.",
    "1075 — Comienza la construcción de la Catedral de Santiago de Compostela.",
    "1833 — Galicia queda organizada en sus cuatro provincias: A Coruña, Lugo, Ourense y Pontevedra.",
    # geography
    "2009 — La Torre de Hércules de A Coruña, el faro romano en funcionamiento más antiguo del mundo, es declarada Patrimonio de la Humanidad.",
    "2002 — Las Illas Cíes, en la ría de Vigo, se integran en el Parque Nacional das Illas Atlánticas de Galicia.",
    "Fisterra, en la Costa da Morte, fue considerada por los romanos el finis terrae: el fin del mundo conocido.",
    "La Ribeira Sacra, en los cañones del Sil y el Miño, reúne la mayor concentración de monasterios románicos de Europa.",
]

# Offline fallback: one notable anecdote per key date. Partial coverage on
# purpose — only used when the API does not respond.
FALLBACK_ES = {
    "01-01": "1959 — Fidel Castro entra triunfalmente en La Habana, marcando el fin del régimen de Batista en Cuba.",
    "01-27": "1945 — El Ejército Rojo libera el campo de concentración de Auschwitz-Birkenau.",
    "02-11": "1990 — Nelson Mandela es liberado tras 27 años en prisión.",
    "03-14": "1879 — Nace Albert Einstein en Ulm, Reino de Württemberg.",
    "04-12": "1961 — Yuri Gagarin se convierte en el primer humano en viajar al espacio exterior.",
    "05-08": "1945 — Alemania nazi firma su rendición incondicional, terminando la Segunda Guerra Mundial en Europa.",
    "05-26": "1828 — Aparece misteriosamente el joven Kaspar Hauser en Núremberg, dando origen a uno de los enigmas históricos más célebres de Europa.",
    "06-06": "1944 — Día D: las fuerzas aliadas desembarcan en las playas de Normandía.",
    "07-04": "1776 — Las Trece Colonias adoptan la Declaración de Independencia de los Estados Unidos.",
    "07-20": "1969 — Neil Armstrong pisa la Luna durante la misión Apolo 11.",
    "08-15": "1945 — Japón anuncia su rendición, poniendo fin a la Segunda Guerra Mundial.",
    "09-11": "2001 — Atentados terroristas contra las Torres Gemelas y el Pentágono.",
    "10-12": "1492 — Cristóbal Colón llega al continente americano, desembarcando en la isla de Guanahaní.",
    "11-09": "1989 — Cae el Muro de Berlín tras 28 años dividiendo la ciudad alemana.",
    "12-10": "1948 — La Asamblea General de la ONU adopta la Declaración Universal de los Derechos Humanos.",
    "12-25": "800 — Carlomagno es coronado emperador del Sacro Imperio Romano por el papa León III.",
}


def _format(evt):
    """Return 'YEAR — text', or None if the event is incomplete."""
    year = evt.get("year")
    text = (evt.get("text") or "").strip()
    if year is None or not text:
        return None
    return f"{year} — {text}"


def _is_cultural(evt) -> bool:
    text = (evt.get("text") or "").lower()
    return any(kw in text for kw in CULTURAL_KEYWORDS)


def fetch_wikipedia_event(month: int, day: int):
    """Return 'YEAR — text' with a cultural bias, or None on network failure.

    Priority: cultural (film/music/art/literature) > 'selected' (Wikipedia's
    curated most-relevant events of the day, where war/politics only appears
    if it is the day's headline) > 'events' (broad pool).
    """
    url = WIKIPEDIA_URL.format(month=month, day=day)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECS) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    selected = payload.get("selected") or []
    events = payload.get("events") or []

    cultural = [e for e in (selected + events) if _is_cultural(e)]
    if cultural:
        return _format(random.choice(cultural))
    if selected:
        return _format(random.choice(selected))
    if events:
        return _format(random.choice(events))
    return None


def main() -> None:
    today = datetime.now()
    month, day = today.month, today.day
    date_es = f"{day} de {MESES_ES[month - 1]}"

    # Galicia roll: date-independent and already Spanish, but presented with
    # the SAME header as any other anecdote so the rule stays transparent.
    if random.random() < GALICIA_CHANCE:
        event = random.choice(GALICIA_EFEMERIDES)
        source = "efeméride cultural gallega (curada, ya en español)"
        lang_note = "(ya está en español, no la traduzcas)"
    else:
        event = fetch_wikipedia_event(month, day)
        source = "Wikipedia (inglés — traducir al español)" if event else None
        if not event:
            event = FALLBACK_ES.get(f"{month:02d}-{day:02d}")
            source = "fallback local (ya en español)" if event else None
        lang_note = "(tradúcela al español si la fuente viene en inglés)"

    header = f"📅 Un {date_es} como hoy…"

    if not event:
        # No anecdote available: inject nothing so we don't pollute context.
        sys.exit(0)

    greeting = random.choice(GREETINGS)

    directive = (
        f"Hoy es {date_es}. Efeméride disponible (fuente: {source}):\n\n"
        f">>> {event}\n\n"
        f"INSTRUCCIÓN PARA TU PRIMERA RESPUESTA EN ESTA SESIÓN:\n"
        f"Antes de abordar la petición del usuario, abre con esta estructura EXACTA:\n\n"
        f"1) Saludo verbatim (cópialo tal cual, respetando puntuación, mayúsculas y "
        f"repeticiones — es así a propósito):\n"
        f"   {greeting}\n\n"
        f"2) Salto de línea, y a continuación el encabezado "
        f"\"{header}\" seguido de la efeméride en español {lang_note}, "
        f"en 1 o 2 frases.\n\n"
        f"3) Salto de línea, y entonces atiende normalmente la petición del usuario.\n\n"
        f"NO repitas el saludo ni la efeméride en respuestas posteriores de la misma sesión."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": directive,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
