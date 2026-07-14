#!/usr/bin/env python3
"""SessionStart hook — injects a historical "on this day" anecdote.

Strategy:
  1. If today matches a dated Galician efeméride (GALICIA_EFEMERIDES), inject
     it instead of the day's event — a real on-this-day event, ≥2 per month.
  2. Otherwise query Wikipedia's public "On This Day" API, biasing selection
     toward favorite fan topics (FAVORITE_TERMS) first, then cultural events
     (film/music/art/literature) over war/politics.
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

# Favorite topics: if the day's Wikipedia list contains an event about one of
# these, it wins over generic cultural events. Distinctive multi-word terms so
# a plain substring match doesn't false-positive (e.g. "super mario", not
# "mario", which would hit any person named Mario). Matched lowercase.
FAVORITE_TERMS = (
    # The Beatles (music)
    "the beatles", "john lennon", "paul mccartney", "george harrison", "ringo starr",
    # Studio Ghibli (animation)
    "studio ghibli", "hayao miyazaki", "isao takahata", "spirited away",
    # Tolkien (literature)
    "tolkien", "lord of the rings", "the hobbit", "silmarillion", "middle-earth",
    # Harry Potter (literature)
    "harry potter", "j. k. rowling", "j.k. rowling",
    # Pokémon (video games)
    "pokémon", "pokemon",
    # The Legend of Zelda (video games)
    "legend of zelda",
    # Super Mario Bros (video games)
    "super mario", "mario bros",
    # Science-fiction cinema
    "science fiction film", "science-fiction film", "sci-fi film",
    "blade runner", "back to the future", "gattaca", "2001: a space odyssey",
)

# Dated Galician efemérides — real events tied to an exact day of Galicia or of
# Galician figures. Key "MM-DD". Injected ONLY on the matching day, where it
# wins over Wikipedia (and skips the network call). Curated with ≥2 per month
# (here ~3-4) to guarantee frequency; all dates web-verified.
GALICIA_EFEMERIDES = {
    "01-05": "1936 — Muere en Santiago de Compostela el escritor Ramón María del Valle-Inclán, gran renovador del teatro español y creador del esperpento.",
    "01-07": "1950 — Muere en el exilio, en Buenos Aires, Alfonso Daniel Rodríguez Castelao, máxima figura del galleguismo y la cultura gallega del siglo XX.",
    "01-15": "2012 — Fallece Manuel Fraga Iribarne, fundador del Partido Popular y presidente de la Xunta de Galicia entre 1990 y 2005.",
    "01-30": "1886 — Nace en Rianxo (A Coruña) Castelao, escritor, dibujante, médico y político, uno de los padres del nacionalismo gallego.",
    "01-31": "1820 — Nace en Ferrol Concepción Arenal, pensadora, escritora y pionera del feminismo y del reformismo penitenciario en España.",
    "02-04": "1893 — Muere en Vigo Concepción Arenal, escritora y activista ferrolana precursora de la defensa de los derechos humanos en España.",
    "02-08": "1835 — Nace en Ponteceso (A Coruña) el poeta Eduardo Pondal, autor de la letra del himno gallego, 'Os pinos'.",
    "02-28": "1981 — Muere en Vigo Álvaro Cunqueiro, novelista, poeta y periodista, una de las grandes figuras literarias gallegas del siglo XX.",
    "03-05": "1888 — Nace en Ourense Ramón Otero Pedrayo, escritor y figura central de la Xeración Nós y de la cultura gallega.",
    "03-07": "1908 — Muere en La Habana el poeta y periodista ourensano Manuel Curros Enríquez, una de las voces clave del Rexurdimento gallego.",
    "03-08": "1917 — Muere en A Coruña el poeta Eduardo Pondal, 'o bardo', autor de la letra del himno de Galicia.",
    "04-10": "1976 — Muere en Ourense el escritor Ramón Otero Pedrayo, una de las grandes figuras de la literatura gallega y del galleguismo del siglo XX.",
    "04-21": "1211 — El arzobispo Pedro Muñiz consagra la Catedral de Santiago de Compostela, en presencia del rey Alfonso IX de León y Galicia.",
    "04-29": "1964 — Muere en Madrid el escritor y periodista coruñés Wenceslao Fernández Flórez, autor de 'El bosque animado'.",
    "05-11": "1916 — Nace en Iria Flavia (Padrón, A Coruña) Camilo José Cela, escritor gallego y Premio Nobel de Literatura en 1989.",
    "05-12": "1921 — Muere en Madrid la escritora coruñesa Emilia Pardo Bazán, figura clave del naturalismo y de la narrativa española.",
    "05-17": "1963 — Se celebra por primera vez el Día das Letras Galegas, instaurado por la Real Academia Galega y dedicado a Rosalía de Castro.",
    "05-31": "1915 — Nace en Láncara (Lugo) Ramón Piñeiro, intelectual galleguista, fundador de la editorial Galaxia y homenajeado en las Letras Galegas de 2009.",
    "06-13": "1910 — Nace en Ferrol el escritor Gonzalo Torrente Ballester, autor de 'Los gozos y las sombras' y Premio Cervantes 1985.",
    "06-27": "2009 — La UNESCO declara Patrimonio de la Humanidad la Torre de Hércules de A Coruña, único faro romano del mundo aún en funcionamiento.",
    "06-28": "1936 — El pueblo gallego aprueba en plebiscito el Estatuto de Autonomía de Galicia, último gran acto político antes de la Guerra Civil.",
    "07-12": "1900 — Nace en Rianxo el poeta Manuel Antonio (Pérez Sánchez), gran figura de la vanguardia gallega y autor de 'De catro a catro'.",
    "07-15": "1885 — Muere en Padrón Rosalía de Castro, poeta y novelista, figura central del Rexurdimento y de la lírica gallega moderna.",
    "07-25": "1920 — Se celebra por primera vez el Día Nacional de Galicia (Día da Patria Galega), acordado por las Irmandades da Fala en la fiesta del Apóstol Santiago.",
    "07-30": "1858 — Muere ahogado en la playa de San Amaro (A Coruña) el poeta compostelano Aurelio Aguirre, el 'Espronceda gallego', con solo 25 años.",
    "08-17": "1936 — Es fusilado en A Caeira (Poio) Alexandre Bóveda, dirigente del Partido Galeguista; la fecha se recuerda como Día da Galiza Mártir.",
    "08-23": "1923 — Se funda en Vigo el Real Club Celta de Vigo, fruto de la fusión del Real Fortuna y el Vigo Sporting.",
    "08-29": "1924 — Muere en Bergondo, con 37 años, el filósofo y pedagogo galleguista Xohán Vicente Viqueira, miembro de las Irmandades da Fala.",
    "09-08": "2004 — Muere en A Coruña el poeta Manuel María (Fernández Teixeiro), voz esencial de las letras gallegas, homenajeado en las Letras Galegas de 2016.",
    "09-14": "1897 — Nace en Ourense el escritor Eduardo Blanco Amor, autor de 'A esmorga', a quien se dedicó el Día das Letras Galegas de 1993.",
    "09-15": "1851 — Nace en Celanova (Ourense) el poeta Manuel Curros Enríquez, uno de los grandes nombres del Rexurdimento gallego.",
    "09-16": "1851 — Nace en A Coruña la escritora Emilia Pardo Bazán, novelista e introductora del naturalismo en España.",
    "10-06": "1929 — Nace en Outeiro de Rei (Lugo) el poeta Manuel María, figura central de la literatura gallega y Día das Letras Galegas 2016.",
    "10-24": "1866 — Muere en Cuntis Domingo Fontán, matemático y geógrafo gallego, autor de la primera Carta Geométrica de Galicia (1834).",
    "10-28": "1866 — Nace en Vilanova de Arousa (Pontevedra) el escritor gallego Ramón María del Valle-Inclán, creador del esperpento.",
    "10-30": "1999 — Muere en Santiago de Compostela el poeta gallego Uxío Novoneyra, autor de 'Os Eidos' y voz del Courel.",
    "11-03": "1928 — Nace en Gres, Vila de Cruces (Pontevedra), el escritor gallego Xosé Neira Vilas, autor de 'Memorias dun neno labrego'.",
    "11-13": "2002 — El petrolero Prestige sufre una avería en un temporal frente a la Costa da Morte e inicia el vertido de fuel que devastó la costa gallega.",
    "11-19": "2002 — El Prestige se parte en dos y se hunde a unos 250 km de Galicia, provocando una de las mayores catástrofes ambientales de la navegación.",
    "11-23": "1922 — Nace en Vilalba (Lugo) Manuel Fraga Iribarne, ministro franquista, fundador de AP/PP y presidente de la Xunta de Galicia (1990-2005).",
    "11-27": "2015 — Muere en Gres (Pontevedra) el escritor gallego Xosé Neira Vilas, referente de la identidad gallega y de la emigración.",
    "12-20": "1907 — Se estrena el himno gallego 'Os Pinos' (letra de Eduardo Pondal, música de Pascual Veiga) en el Centro Gallego de La Habana.",
    "12-21": "1980 — Galicia aprueba en referéndum su Estatuto de Autonomía, con el 78,8% de votos a favor.",
    "12-22": "1911 — Nace en Mondoñedo (Lugo) el escritor gallego Álvaro Cunqueiro, autor de 'Merlín e familia' y Día das Letras Galegas 1991.",
}

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


def _is_favorite(evt) -> bool:
    text = (evt.get("text") or "").lower()
    return any(term in text for term in FAVORITE_TERMS)


def fetch_wikipedia_event(month: int, day: int):
    """Return 'YEAR — text' with a cultural bias, or None on network failure.

    Priority: favorite (curated fan topics) > cultural (film/music/art/
    literature) > 'selected' (Wikipedia's curated most-relevant events of the
    day, where war/politics only appears if it is the day's headline) >
    'events' (broad pool).
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

    favorite = [e for e in (selected + events) if _is_favorite(e)]
    if favorite:
        return _format(random.choice(favorite))
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

    # Galician efeméride: if today has a dated Galician event it wins over
    # Wikipedia and skips the network call. It is a real "on this day" event,
    # so it uses the SAME header as any other anecdote — no special-casing.
    galicia_ef = GALICIA_EFEMERIDES.get(f"{month:02d}-{day:02d}")
    if galicia_ef:
        event = galicia_ef
        source = "efeméride gallega (curada y verificada, ya en español)"
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
