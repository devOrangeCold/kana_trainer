import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER, END
import sqlite3
import uuid
import datetime
import time
import random
import asyncio
import threading
from pathlib import Path

class KanaTrainer(toga.App):
    def startup(self):
        self.main_window = toga.MainWindow(title=self.formal_name)
        
        try:
            data_dir = self.paths.data
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "kana_fluency.db"
        except Exception:
            self.db_path = Path("kana_fluency.db").absolute()
            
        self.init_db()
        self.timer_task = None 
        self.is_revealed = False
        self.is_timeout = False
        self.current_finalize_func = None
        self.current_reveal_func = None

        self.show_deck_view()
        self.main_window.show()

    def init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS decks (id INTEGER PRIMARY KEY, name TEXT, locked INTEGER DEFAULT 0)')
        c.execute('''CREATE TABLE IF NOT EXISTS cards 
                     (card_hash TEXT PRIMARY KEY, deck_id INTEGER, question TEXT, answer TEXT, 
                      level INTEGER DEFAULT 0, streak INTEGER DEFAULT 0, mastered INTEGER DEFAULT 0)''')
        c.execute('CREATE TABLE IF NOT EXISTS stats (card_hash TEXT, rx REAL, success INTEGER, timestamp TEXT)')
        
        if not c.execute("SELECT * FROM decks").fetchall():
            c.executemany("INSERT INTO decks VALUES (?, ?, 0)", [
                (1, 'Hiragana Basics'), (2, 'Katakana Basics'), 
                (3, 'Hiragana Words'), (4, 'Katakana Words'), 
                (5, 'Hiragana Paragraphs'), (6, 'Katakana Paragraphs')
            ])

        # SEEDING LOGIC
        # Hiragana Basics (Deck 1)
        if not c.execute("SELECT * FROM cards WHERE deck_id=1").fetchone():
            h_chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"
            h_roms = ["a","i","u","e","o","ka","ki","ku","ke","ko","sa","shi","su","se","so","ta","chi","tsu","te","to","na","ni","nu","ne","no","ha","hi","fu","he","ho"]
            for k, r in zip(h_chars, h_roms):
                c.execute("INSERT INTO cards (card_hash, deck_id, question, answer) VALUES (?, 1, ?, ?)", (str(uuid.uuid4())[:8], k, r))

        # Katakana Basics (Deck 2)
        if not c.execute("SELECT * FROM cards WHERE deck_id=2").fetchone():
            k_chars = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホ"
            k_roms = ["a","i","u","e","o","ka","ki","ku","ke","ko","sa","shi","su","se","so","ta","chi","tsu","te","to","na","ni","nu","ne","no","ha","hi","fu","he","ho"]
            for k, r in zip(k_chars, k_roms):
                c.execute("INSERT INTO cards (card_hash, deck_id, question, answer) VALUES (?, 2, ?, ?)", (str(uuid.uuid4())[:8], k, r))

        # Hiragana Words (Deck 3) - Example seed
        if not c.execute("SELECT * FROM cards WHERE deck_id=3").fetchone():
            h_words = [("ねこ", "neko"), ("いぬ", "inu"), ("さくら", "sakura"), ("すし", "sushi"), ("みず", "mizu"), ("とり", "tori"), ("やま", "yama"), ("うみ", "umi"), ("はな", "hana"), ("くま", "kuma")]
            for q, a in h_words:
                c.execute("INSERT INTO cards (card_hash, deck_id, question, answer) VALUES (?, 3, ?, ?)", (str(uuid.uuid4())[:8], q, a))

        # Katakana Words (Deck 4) - Example seed
        if not c.execute("SELECT * FROM cards WHERE deck_id=4").fetchone():
            k_words = [("カメラ", "kamera"), ("テレビ", "terebi"), ("パン", "pan"), ("トイレ", "toire"), ("コーヒー", "koohii"), ("バス", "basu"), ("ホテル", "hoteru"), ("ドア", "doa"), ("タクシー", "takushii"), ("アイス", "aisu")]
            for q, a in k_words:
                c.execute("INSERT INTO cards (card_hash, deck_id, question, answer) VALUES (?, 4, ?, ?)", (str(uuid.uuid4())[:8], q, a))

        conn.commit()
        conn.close()

    def db_write_sync(self, query, params=()):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(query, params)
        conn.commit()
        conn.close()

    def show_deck_view(self, widget=None):
        if self.timer_task: self.timer_task.cancel()
        self.is_timeout = False
        main_box = toga.Box(style=Pack(direction=COLUMN, margin=20))
        main_box.add(toga.Label("KANA SPEED TRAINER", style=Pack(font_size=18, font_weight='bold', margin_bottom=20, text_align='center')))

        conn = sqlite3.connect(str(self.db_path))
        decks = conn.execute("SELECT * FROM decks ORDER BY id ASC").fetchall()
        for d_id, d_name, _ in decks:
            count_data = conn.execute(f"SELECT COUNT(*), SUM(mastered) FROM cards WHERE deck_id={d_id}").fetchone()
            total, mastered = count_data[0] or 0, count_data[1] or 0
            is_done = (total > 0 and total == mastered)
            label = f"🔥 {d_name} (mastered)" if is_done else f"🔥 {d_name}"
            
            row = toga.Box(style=Pack(direction=ROW, margin_bottom=10, align_items='center'))
            btn = toga.Button(label, on_press=lambda w, d=d_id: self.start_session(d), style=Pack(flex=1, height=45))
            check_color = "#28a745" if is_done else "#e9ecef"
            check_btn = toga.Button("✓", on_press=lambda w, d=d_id, m=is_done: self.toggle_mastery(d, m), 
                                    style=Pack(width=40, height=45, margin_left=5, background_color=check_color))
            row.add(btn); row.add(check_btn); main_box.add(row)
        conn.close(); self.main_window.content = main_box

    def toggle_mastery(self, deck_id, currently_mastered):
        new_state = 0 if currently_mastered else 1
        lvl = 0 if currently_mastered else 2
        self.db_write_sync("UPDATE cards SET mastered=?, level=? WHERE deck_id=?", (new_state, lvl, deck_id))
        self.show_deck_view()

    def start_session(self, deck_id):
        if deck_id >= 5: 
            asyncio.create_task(self.start_paragraph_session(deck_id))
            return

        conn = sqlite3.connect(str(self.db_path)); conn.row_factory = sqlite3.Row
        q = conn.execute("SELECT * FROM cards WHERE deck_id=?", (deck_id,)).fetchall()
        conn.close()
        
        if not q:
            asyncio.create_task(self.main_window.dialog(toga.InfoDialog("Empty Deck", f"No cards in Deck {deck_id}.")))
            return

        session_q = random.sample(q, min(20, len(q)))
        asyncio.create_task(self.render_card(session_q, 0, deck_id))

    # --- PARAGRAPH MODE ---
    async def start_paragraph_session(self, deck_id):
        conn = sqlite3.connect(str(self.db_path)); conn.row_factory = sqlite3.Row
        word_deck = 3 if deck_id == 5 else 4
        words = [r['question'] for r in conn.execute("SELECT question FROM cards WHERE deck_id=?", (word_deck,)).fetchall()]
        conn.close()

        if len(words) < 10:
            await self.main_window.dialog(toga.InfoDialog("Missing Words", f"You need at least 10 words in Deck {word_deck} to generate paragraphs."))
            return

        para_words = random.sample(words, 10)
        start_time = time.time()

        outer = toga.Box(style=Pack(direction=COLUMN, padding=20, background_color="white"))
        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=20))
        header.add(toga.Button("BACK", on_press=self.show_deck_view, style=Pack(width=70)))
        timer_label = toga.Label("0.0s", style=Pack(flex=1, text_align='center', font_size=16, font_weight='bold'))
        header.add(timer_label); outer.add(header)

        # 5x2 Grid
        grid = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER, margin_top=30))
        r1, r2 = toga.Box(style=Pack(direction=ROW)), toga.Box(style=Pack(direction=ROW, margin_top=20))
        for i, word in enumerate(para_words):
            lbl = toga.Label(word, style=Pack(font_size=24, margin=12))
            if i < 5: r1.add(lbl)
            else: r2.add(lbl)
        grid.add(r1); grid.add(r2); outer.add(grid)

        async def end_para(w):
            elapsed = time.time() - start_time
            self.db_write_sync("INSERT INTO stats (card_hash, rx, success, timestamp) VALUES (?,?,?,?)", 
                               (f"PARA_{deck_id}", round(elapsed, 2), 1, datetime.datetime.now().isoformat()))
            self.show_analytics(deck_id)

        footer = toga.Box(style=Pack(direction=ROW, margin_top=40))
        footer.add(toga.Button("DONE", on_press=end_para, style=Pack(flex=1, height=60, background_color="green", color="white")))
        outer.add(footer); self.main_window.content = outer

        async def update_clock():
            while True:
                timer_label.text = f"{time.time() - start_time:.1f}s"
                await asyncio.sleep(0.1)
        self.timer_task = asyncio.create_task(update_clock())

    # --- STUDY RENDERER ---
    async def render_card(self, queue, index, deck_id):
        card = queue[index]
        self.start_time = time.time()
        self.is_revealed, self.is_timeout = False, False
        limit = {0: 5.0, 1: 3.0, 2: 2.0}.get(card['level'], 5.0)
        ticks = int(limit * 10)

        outer = toga.Box(style=Pack(direction=COLUMN, background_color="white"))
        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin=10))
        header.add(toga.Button("BACK", on_press=self.show_deck_view, style=Pack(width=70)))
        header.add(toga.Label(f" {len(queue)-index} LEFT", style=Pack(flex=1, font_weight='bold', text_align='center')))
        outer.add(header)

        self.content_box = toga.Box(style=Pack(direction=COLUMN, margin=30, align_items=CENTER))
        self.throbber = toga.ProgressBar(max=ticks, value=ticks, style=Pack(width=300, margin_bottom=40))
        self.content_box.add(self.throbber)
        self.content_box.add(toga.Label(card['question'], style=Pack(font_size=80, text_align=CENTER, width=350)))
        outer.add(self.content_box); self.controls = toga.Box(style=Pack(direction=ROW, margin=20)); outer.add(self.controls)
        
        self.main_window.content = outer
        self.main_window.on_key_press = self.on_key_press

        async def finalize(success):
            if self.timer_task: self.timer_task.cancel()
            rx_t = round(time.time() - self.start_time, 3)
            self.db_write_sync("INSERT INTO stats VALUES (?,?,?,?)", (card['card_hash'], rx_t, int(success), datetime.datetime.now().isoformat()))
            if index + 1 < len(queue): await self.render_card(queue, index+1, deck_id)
            else: self.show_analytics(deck_id)

        def reveal(w):
            if self.is_revealed: return
            if self.timer_task: self.timer_task.cancel()
            self.is_revealed = True
            self.content_box.add(toga.Label(card['answer'], style=Pack(font_size=45, color="#dc3545", margin_top=20, text_align=CENTER, width=350)))
            self.controls.clear()
            self.controls.add(toga.Button("NO", on_press=lambda w: asyncio.create_task(finalize(False)), style=Pack(flex=1, height=60)))
            self.controls.add(toga.Button("YES", on_press=lambda w: asyncio.create_task(finalize(True)), style=Pack(flex=1, height=60, margin_left=10)))

        self.current_reveal_func, self.current_finalize_func = reveal, finalize
        self.controls.add(toga.Button("REVEAL", on_press=reveal, style=Pack(flex=1, height=60)))
        
        async def run_timer():
            for i in range(ticks, -1, -1):
                await asyncio.sleep(0.1); self.throbber.value = i
            self.is_timeout, self.is_revealed = True, True
            self.content_box.add(toga.Label(card['answer'], style=Pack(font_size=45, color="#6c757d", margin_top=20, text_align=CENTER, width=350)))
            self.controls.clear()
            self.controls.add(toga.Button("TOO SLOW", on_press=lambda w: asyncio.create_task(finalize(False)), style=Pack(flex=1, height=60, background_color="#343a40", color="white")))
        self.timer_task = asyncio.create_task(run_timer())

    def on_key_press(self, widget, key, modifiers):
        if self.is_timeout: asyncio.create_task(self.current_finalize_func(False))
        elif not self.is_revealed and self.current_reveal_func: self.current_reveal_func(None)
        elif self.is_revealed and self.current_finalize_func:
            if key == toga.Key.LEFT: asyncio.create_task(self.current_finalize_func(False))
            elif key == toga.Key.RIGHT: asyncio.create_task(self.current_finalize_func(True))

    def show_analytics(self, deck_id):
        if self.timer_task: self.timer_task.cancel()
        outer = toga.Box(style=Pack(direction=COLUMN, margin=15, align_items=CENTER, background_color="white"))
        
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        # 1. FETCH DATA
        # Graph Data: Last 20 Sessions for this Deck
        if deck_id >= 5:
            p_id = f"PARA_{deck_id}"
            history = conn.execute("SELECT rx FROM stats WHERE card_hash=? ORDER BY timestamp DESC LIMIT 20", (p_id,)).fetchall()
            best = conn.execute("SELECT MIN(rx) FROM stats WHERE card_hash=?", (p_id,)).fetchone()[0]
        else:
            history = conn.execute('''SELECT AVG(rx) as avg_rx FROM stats 
                                     JOIN cards ON stats.card_hash = cards.card_hash 
                                     WHERE cards.deck_id=? GROUP BY timestamp ORDER BY timestamp DESC LIMIT 20''', (deck_id,)).fetchall()
            best = conn.execute('''SELECT MIN(rx) FROM stats JOIN cards ON stats.card_hash = cards.card_hash 
                                  WHERE cards.deck_id=?''', (deck_id,)).fetchone()[0]

        # 2. RENDER TOP STATS
        if history:
            last_run = history[0][0]
            outer.add(toga.Label(f"LAST: {last_run:.2f}s  |  BEST: {best:.2f}s", style=Pack(font_size=14, font_weight='bold', margin_bottom=10)))

        # 3. RENDER SPEED GRAPH
        graph_box = toga.Box(style=Pack(direction=ROW, height=100, align_items=END, background_color="#f8f9fa", width=360))
        if history:
            max_val = max([r[0] for r in history]) if history else 10
            for r in reversed(history):
                h = max(5, int((r[0] / max_val) * 100))
                graph_box.add(toga.Box(style=Pack(width=12, height=h, background_color="#007bff", margin_left=5)))
        outer.add(graph_box)

        # 4. RENDER HEATMAP (For Basics Decks 1 & 2 Only)
        if deck_id <= 2:
            outer.add(toga.Divider())
            outer.add(toga.Label("PHONETIC MASTERY (Last 10 Attempts)", style=Pack(font_size=14, font_weight='bold', margin_top=15, margin_bottom=10)))
            
            # Fetch last 10 attempts per character
            char_stats = conn.execute('''
                SELECT question, answer, AVG(rx) as avg_rx FROM (
                    SELECT c.question, c.answer, s.rx, 
                    ROW_NUMBER() OVER (PARTITION BY c.question ORDER BY s.timestamp DESC) as rank
                    FROM cards c JOIN stats s ON c.card_hash = s.card_hash
                    WHERE c.deck_id = ?
                ) WHERE rank <= 10 GROUP BY question
            ''', (deck_id,)).fetchall()
            
            avg_map = {s['question']: s['avg_rx'] for s in char_stats}
            
            # Re-generate Gojuon Grid
            vowels, consonants = ['a','i','u','e','o'], ['', 'k','s','t','n','h','m','y','r','w']
            full_deck = conn.execute("SELECT question, answer FROM cards WHERE deck_id=?", (deck_id,)).fetchall()
            romaji_to_kana = {r['answer']: r['question'] for r in full_deck if len(r['question']) == 1}
            
            grid = toga.Box(style=Pack(direction=ROW))
            for c in consonants:
                col_box = toga.Box(style=Pack(direction=COLUMN))
                for v in vowels:
                    r_key = f"{c}{v}"
                    j_char = romaji_to_kana.get(r_key, r_key)
                    avg = avg_map.get(j_char)
                    
                    color = "#f8f9fa" if avg is None else "#f8d7da" if avg > 3.0 else "#fff3cd" if avg > 1.5 else "#d4edda"
                    
                    cell = toga.Box(style=Pack(width=34, height=48, background_color=color, margin=1, align_items=CENTER, direction=COLUMN))
                    cell.add(toga.Label(j_char, style=Pack(font_size=12, font_weight='bold')))
                    cell.add(toga.Label(r_key, style=Pack(font_size=8)))
                    col_box.add(cell)
                grid.add(col_box)
            outer.add(grid)

        conn.close()
        outer.add(toga.Button("DONE", on_press=self.show_deck_view, style=Pack(margin_top=25, width=200, height=45)))
        self.main_window.content = outer

def main():
    return KanaTrainer("kana_trainer", "com.example.kana_trainer")