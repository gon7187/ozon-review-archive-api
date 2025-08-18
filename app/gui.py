import customtkinter as ctk
from tkinter import messagebox, Menu
import threading
from .wb_parser import get_product_id_from_url, fetch_product_data_and_reviews
from .gemini_analyzer import GeminiAnalyzer
import os
import logging

logger = logging.getLogger(__name__)

BG_COLOR = "#000000"
FG_COLOR = "#FFFFFF"
TEXT_COLOR = "#FFFFFF"
BUTTON_COLOR = "#1F1F1F"
BUTTON_HOVER_COLOR = "#333333"
INPUT_BG_COLOR = "#1A1A1A"
BORDER_COLOR = "#404040"
ACCENT_COLOR = "#FFFFFF"
SUCCESS_COLOR = "#2ECC71"
ERROR_COLOR = "#E74C3C"
WARNING_COLOR = "#F39C12"

DEFAULT_REVIEWS_LIMIT = 200
MAX_REVIEWS_LIMIT_INPUT = 5000

class App(ctk.CTk):
    def __init__(self, gemini_api_key: str):
        super().__init__()
        logger.info("Инициализация приложения GUI.")

        if not gemini_api_key:
            logger.error("API ключ Gemini не найден при инициализации GUI.")
            messagebox.showerror("Ошибка конфигурации", "API ключ Gemini не найден. Проверьте файл .env")
            self.destroy()
            return

        try:
            self.gemini_analyzer = GeminiAnalyzer(api_key=gemini_api_key)
            logger.info("Gemini Analyzer успешно инициализирован.")
        except ConnectionError as e:
            logger.error(f"Ошибка соединения при инициализации Gemini Analyzer: {e}")
            messagebox.showerror("Ошибка Gemini API", f"Не удалось инициализировать Gemini Analyzer: {e}")
            self.destroy()
            return
        except ValueError as e:
            logger.error(f"Ошибка значения при инициализации Gemini Analyzer: {e}")
            messagebox.showerror("Ошибка Gemini API", f"Ошибка конфигурации Gemini: {e}")
            self.destroy()
            return

        self.title("WB Review Analyzer")
        self.geometry("900x800") 
        self.configure(fg_color=BG_COLOR)
        
        icon_path_ico = "app/assets/icon.ico" 
        icon_path_png = "app/assets/icon.png"
        try:
            if os.path.exists(icon_path_ico):
                self.iconbitmap(icon_path_ico)
            elif os.path.exists(icon_path_png):
                from PIL import Image, ImageTk
                img = Image.open(icon_path_png)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(32,32))
                pass
        except Exception as e_icon:
            logger.warning(f"Не удалось установить иконку приложения: {e_icon}")
        
        self._create_widgets()
        self._loading_animation_job = None
        self.animation_chars = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
        self.current_animation_char_index = 0
        
        self.url_entry.bind("<Control-v>", lambda event: self.url_entry.event_generate("<<Paste>>"))
        self.url_entry.bind("<Control-c>", lambda event: self.url_entry.event_generate("<<Copy>>"))
        self.url_entry.bind("<Control-x>", lambda event: self.url_entry.event_generate("<<Cut>>"))
        self.url_entry.bind("<Control-a>", lambda event: self.url_entry.select_range(0, 'end'))

    def _create_widgets(self):
        main_frame = ctk.CTkFrame(self, fg_color=BG_COLOR)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        input_controls_frame = ctk.CTkFrame(main_frame, fg_color=BG_COLOR)
        input_controls_frame.pack(pady=(0,15), padx=0, fill="x")

        self.url_label = ctk.CTkLabel(input_controls_frame, text="URL или ID товара WB:", text_color=TEXT_COLOR, font=("Arial", 14))
        self.url_label.pack(side="left", padx=(0, 10))

        self.url_entry = ctk.CTkEntry(input_controls_frame, width=350, font=("Arial", 14),
                                      fg_color=INPUT_BG_COLOR, text_color=TEXT_COLOR,
                                      border_color=BORDER_COLOR, placeholder_text="Ссылка или артикул...")
        self.url_entry.pack(side="left", expand=True, fill="x", padx=(0,10))
        self.url_entry.focus_set()

        self.limit_label = ctk.CTkLabel(input_controls_frame, text="Лимит отзывов:", text_color=TEXT_COLOR, font=("Arial", 14))
        self.limit_label.pack(side="left", padx=(10,5))
        
        self.limit_entry_var = ctk.StringVar(value=str(DEFAULT_REVIEWS_LIMIT))
        self.limit_entry = ctk.CTkEntry(input_controls_frame, textvariable=self.limit_entry_var, width=70, font=("Arial", 14),
                                        fg_color=INPUT_BG_COLOR, text_color=TEXT_COLOR, border_color=BORDER_COLOR)
        self.limit_entry.pack(side="left", padx=(0,10))


        self.analyze_button = ctk.CTkButton(input_controls_frame, text="Анализировать", command=self.start_analysis_thread,
                                            font=("Arial", 14, "bold"), fg_color=BUTTON_COLOR,
                                            hover_color=BUTTON_HOVER_COLOR, text_color=ACCENT_COLOR, width=150)
        self.analyze_button.pack(side="left")

        self.status_frame = ctk.CTkFrame(main_frame, fg_color=BG_COLOR, height=30)
        self.status_frame.pack(pady=(0,10), fill="x")
        
        self.status_label = ctk.CTkLabel(self.status_frame, text="", text_color=TEXT_COLOR, font=("Arial", 12))
        self.status_label.pack(side="left", padx=5)

        self.analyzed_reviews_count_label = ctk.CTkLabel(self.status_frame, text="", text_color=FG_COLOR, font=("Arial", 10))
        self.analyzed_reviews_count_label.pack(side="right", padx=5)

        results_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        results_frame.pack(pady=10, padx=0, fill="both", expand=True)

        results_frame.columnconfigure(0, weight=1)
        results_frame.columnconfigure(1, weight=0, minsize=10)
        results_frame.columnconfigure(2, weight=1) 
        results_frame.rowconfigure(1, weight=1) 

        self.pros_label = ctk.CTkLabel(results_frame, text="✅ Плюсы:", text_color=SUCCESS_COLOR, font=("Arial", 16, "bold"))
        self.pros_label.grid(row=0, column=0, padx=10, pady=(0,5), sticky="w")
        
        self.pros_text = ctk.CTkTextbox(results_frame, wrap="word", state="disabled", font=("Arial", 13),
                                        fg_color=INPUT_BG_COLOR, text_color=TEXT_COLOR,
                                        border_color=BORDER_COLOR, scrollbar_button_color=BUTTON_COLOR,
                                        scrollbar_button_hover_color=BUTTON_HOVER_COLOR)
        self.pros_text.grid(row=1, column=0, padx=(10,5), pady=5, sticky="nsew")
        self._create_context_menu(self.pros_text)

        self.cons_label = ctk.CTkLabel(results_frame, text="❌ Минусы:", text_color=ERROR_COLOR, font=("Arial", 16, "bold"))
        self.cons_label.grid(row=0, column=2, padx=10, pady=(0,5), sticky="w")

        self.cons_text = ctk.CTkTextbox(results_frame, wrap="word", state="disabled", font=("Arial", 13),
                                        fg_color=INPUT_BG_COLOR, text_color=TEXT_COLOR,
                                        border_color=BORDER_COLOR, scrollbar_button_color=BUTTON_COLOR,
                                        scrollbar_button_hover_color=BUTTON_HOVER_COLOR)
        self.cons_text.grid(row=1, column=2, padx=(5,10), pady=5, sticky="nsew")
        self._create_context_menu(self.cons_text)
        
        copy_button_frame = ctk.CTkFrame(main_frame, fg_color=BG_COLOR)
        copy_button_frame.pack(pady=(10,0), fill="x")
        
        self.copy_pros_button = ctk.CTkButton(copy_button_frame, text="Копировать плюсы", 
                                              command=lambda: self._copy_to_clipboard(self.pros_text.get("1.0", "end-1c")),
                                              fg_color=BUTTON_COLOR, hover_color=BUTTON_HOVER_COLOR, text_color=ACCENT_COLOR)
        self.copy_pros_button.pack(side="left", padx=10, expand=True)
        
        self.copy_cons_button = ctk.CTkButton(copy_button_frame, text="Копировать минусы", 
                                              command=lambda: self._copy_to_clipboard(self.cons_text.get("1.0", "end-1c")),
                                              fg_color=BUTTON_COLOR, hover_color=BUTTON_HOVER_COLOR, text_color=ACCENT_COLOR)
        self.copy_cons_button.pack(side="right", padx=10, expand=True)

    def _create_context_menu(self, widget):
        menu = Menu(widget, tearoff=0, background=INPUT_BG_COLOR, foreground=TEXT_COLOR, 
                    activebackground=BUTTON_HOVER_COLOR, activeforeground=TEXT_COLOR,
                    relief="flat", borderwidth=1)
        menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"), state="disabled")
        menu.add_command(label="Выделить всё", command=lambda: widget.select_range(0, 'end'))
        
        def show_menu(event):
            widget.focus_set() 
            try:
                if widget.tag_ranges("sel"):
                    menu.entryconfig("Копировать", state="normal")
                else:
                    menu.entryconfig("Копировать", state="disabled")
            except: 
                menu.entryconfig("Копировать", state="disabled")
            menu.tk_popup(event.x_root, event.y_root)
        
        widget.bind("<Button-3>", show_menu)

    def _copy_to_clipboard(self, text_to_copy):
        if not text_to_copy or text_to_copy.strip() == "Не найдено":
            self._update_status("Нечего копировать.", status_type="warning", duration=2000)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text_to_copy)
            self._update_status("Результаты скопированы!", status_type="success", duration=2000)
            logger.info("Текст скопирован в буфер обмена.")
        except Exception as e_clip:
            self._update_status(f"Ошибка копирования: {e_clip}", status_type="error", duration=3000)
            logger.error(f"Ошибка копирования в буфер: {e_clip}")

    def _update_status(self, message: str, is_loading: bool = False, status_type: str = "info", duration: int = 0):
        color_map = {
            "info": TEXT_COLOR, "success": SUCCESS_COLOR,
            "warning": WARNING_COLOR, "error": ERROR_COLOR
        }
        current_color = color_map.get(status_type, TEXT_COLOR)
        self.status_label.configure(text_color=current_color)

        if is_loading:
            char = self.animation_chars[self.current_animation_char_index]
            self.status_label.configure(text=f"{message} {char}")
        else:
            self.status_label.configure(text=message)
        
        if hasattr(self, "_status_clear_job"):
             if self._status_clear_job: self.after_cancel(self._status_clear_job)
        
        if duration > 0 and not is_loading:
            self._status_clear_job = self.after(duration, lambda: self.status_label.configure(text="", text_color=TEXT_COLOR))
        else:
            self._status_clear_job = None


    def _animate_loading(self, base_message: str):
        if not self._loading_animation_job: return
        self.current_animation_char_index = (self.current_animation_char_index + 1) % len(self.animation_chars)
        self._update_status(base_message, is_loading=True)
        self._loading_animation_job = self.after(150, lambda msg=base_message: self._animate_loading(msg))

    def _start_loading_animation(self, base_message: str):
        self.current_animation_char_index = 0
        if self._loading_animation_job: self.after_cancel(self._loading_animation_job)
        self._loading_animation_job = True 
        self.analyzed_reviews_count_label.configure(text="")
        self._animate_loading(base_message)

    def _stop_loading_animation(self, final_message: str = "", status_type: str = "info"):
        if self._loading_animation_job:
            self.after_cancel(self._loading_animation_job)
            self._loading_animation_job = None
        if final_message:
            self._update_status(final_message, status_type=status_type, duration=5000 if status_type != "error" else 0)

    def _clear_results(self):
        for widget in [self.pros_text, self.cons_text]:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
        self.analyzed_reviews_count_label.configure(text="")

    def _display_results(self, pros: list, cons: list, num_reviews_analyzed: int = 0):
        self.pros_text.configure(state="normal")
        self.pros_text.insert("1.0", "\n".join([f"• {p}" for p in pros]) if pros else "Не найдено")
        self.pros_text.configure(state="disabled")

        self.cons_text.configure(state="normal")
        self.cons_text.insert("1.0", "\n".join([f"• {c}" for c in cons]) if cons else "Не найдено")
        self.cons_text.configure(state="disabled")

        if num_reviews_analyzed > 0:
            self.analyzed_reviews_count_label.configure(text=f"Проанализировано: {num_reviews_analyzed} отзыв(ов)")
        else:
             self.analyzed_reviews_count_label.configure(text="")

    def start_analysis_thread(self):
        url_or_id = self.url_entry.get().strip()
        if not url_or_id:
            self._update_status("Введите URL или ID товара.", status_type="warning", duration=3000)
            return

        try:
            reviews_to_analyze = int(self.limit_entry_var.get())
            if not (0 < reviews_to_analyze <= MAX_REVIEWS_LIMIT_INPUT):
                 raise ValueError()
        except ValueError:
            self._update_status(f"Лимит отзывов: число от 1 до {MAX_REVIEWS_LIMIT_INPUT}.", status_type="error", duration=4000)
            return

        self.analyze_button.configure(state="disabled", text="Анализ...")
        self._clear_results()
        self._start_loading_animation("Подготовка...") 

        thread = threading.Thread(target=self.perform_analysis, args=(url_or_id, reviews_to_analyze), daemon=True)
        thread.start()

    def perform_analysis(self, url_or_id: str, reviews_limit: int):
        num_reviews_fetched = 0
        try:
            self.after(0, lambda: self._start_loading_animation("Получение ID..."))
            product_id = get_product_id_from_url(url_or_id)
            
            if not product_id and url_or_id.isdigit(): product_id = url_or_id
            if not product_id: raise ValueError("Некорректный URL или ID.")
            
            self.after(0, lambda pid=product_id: self._start_loading_animation(f"Загрузка данных ID: {pid}..."))
            reviews, product_name, error_msg = fetch_product_data_and_reviews(product_id, reviews_limit=reviews_limit) 
            
            if error_msg: raise Exception(f"{error_msg}")

            if reviews is not None: num_reviews_fetched = len(reviews)

            if not reviews: 
                final_msg = f"Для '{product_name}' текстовые отзывы не найдены."
                self.after(0, lambda msg=final_msg: self._stop_loading_animation(msg, status_type="warning"))
                self.after(0, lambda: self._display_results([], [], num_reviews_analyzed=0))
                logger.warning(f"Отзывы не найдены или пусты для '{product_name}' (ID: {product_id}).")
                return

            self.after(0, lambda name=product_name, num=num_reviews_fetched: self._start_loading_animation(f"Анализ {num} отзыв(ов) для '{name}'..."))
            analysis_result, error_msg_gemini = self.gemini_analyzer.analyze_reviews(reviews, product_name=product_name)
            
            if error_msg_gemini: raise Exception(f"Ошибка Gemini: {error_msg_gemini}")
            if not analysis_result: raise Exception("Gemini не вернул результат.")

            self.after(0, lambda: self._stop_loading_animation("Анализ завершен.", status_type="success"))
            self.after(0, lambda: self._display_results(analysis_result.get("pros", []), 
                                                        analysis_result.get("cons", []),
                                                        num_reviews_analyzed=num_reviews_fetched))
            logger.info(f"Анализ для '{product_name}' (ID: {product_id}) завершен. Проанализировано {num_reviews_fetched} отзывов.")

        except ValueError as ve:
            self.after(0, lambda err=ve: self._stop_loading_animation(f"Ошибка: {err}", status_type="error"))
            self.after(0, lambda err=ve: messagebox.showerror("Ошибка валидации", str(err)))
            logger.error(f"Ошибка валидации при анализе '{url_or_id}': {ve}")
        except ConnectionError as ce:
            self.after(0, lambda err=ce: self._stop_loading_animation(f"Ошибка соединения: {err}", status_type="error"))
            self.after(0, lambda err=ce: messagebox.showerror("Ошибка соединения", str(err)))
            logger.error(f"Ошибка соединения при анализе '{url_or_id}': {ce}")
        except Exception as e_exc: 
            self.after(0, lambda err=e_exc: self._stop_loading_animation(f"Ошибка: {err}", status_type="error"))
            self.after(0, lambda err=e_exc: messagebox.showerror("Ошибка", f"Непредвиденная ошибка: {err}"))
            logger.exception(f"Непредвиденная ошибка при анализе '{url_or_id}': {e_exc}")
        finally:
            self.after(0, lambda: self.analyze_button.configure(state="normal", text="Анализировать"))

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Запуск gui.py напрямую для тестирования.")
    from dotenv import load_dotenv
    
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if not os.path.exists(dotenv_path):
        dotenv_path = '.env' 
        
    loaded = load_dotenv(dotenv_path=dotenv_path)
    if loaded: logger.info(f".env файл загружен из: {dotenv_path}")
    else: logger.warning(f".env файл не найден.")
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key: logger.error("GEMINI_API_KEY не найден.")
    
    app = App(gemini_api_key=gemini_key if gemini_key else "DUMMY_KEY_GUI_TEST")
    if app.winfo_exists(): app.mainloop()
    else: logger.error("Окно приложения не было создано.")