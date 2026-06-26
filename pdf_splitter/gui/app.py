"""CustomTkinter GUI for the PDF splitter."""

import threading
import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..core.naming import PageInfo, analyze_page, build_filename, sanitize_filename_part

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class PageRow(ctk.CTkFrame):
    """One row in the page preview table."""

    def __init__(self, master, page_num: int, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.page_num = page_num

        # Page number label
        self.lbl_page = ctk.CTkLabel(self, text=str(page_num), width=50, anchor="center")
        self.lbl_page.grid(row=0, column=0, padx=(5, 2), pady=1, sticky="ew")

        # Drawing number (editable)
        self.entry_dn = ctk.CTkEntry(self, width=120)
        self.entry_dn.grid(row=0, column=1, padx=2, pady=1)

        # Drawing name (editable)
        self.entry_name = ctk.CTkEntry(self, width=260)
        self.entry_name.grid(row=0, column=2, padx=2, pady=1)

        # Output filename (read-only preview)
        self.lbl_filename = ctk.CTkLabel(self, text="", width=380, anchor="w",
                                         fg_color="#eeeeee", corner_radius=4)

        self.grid_columnconfigure(2, weight=1)

    def set_values(self, dn: str, name: str):
        self.entry_dn.delete(0, "end")
        self.entry_dn.insert(0, dn)
        self.entry_name.delete(0, "end")
        self.entry_name.insert(0, name)
        self._update_filename()

    def get_values(self) -> tuple[str, str]:
        return self.entry_dn.get().strip(), self.entry_name.get().strip()

    def _update_filename(self):
        dn = self.entry_dn.get().strip() or "无图号"
        name = self.entry_name.get().strip() or "无图名"
        dn_safe = sanitize_filename_part(dn)
        name_safe = sanitize_filename_part(name)
        fname = f"{self.page_num}_{dn_safe}_{name_safe}.pdf"
        self.lbl_filename.configure(text=fname)

    def on_edit(self, event=None):
        self._update_filename()

    def bind_edit_callback(self):
        self.entry_dn.bind("<KeyRelease>", self.on_edit)
        self.entry_name.bind("<KeyRelease>", self.on_edit)


class App(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("PDF拆分器 - 审图用")
        self.geometry("960x700")
        self.minsize(800, 500)

        self._pdf_path: str | None = None
        self._page_infos: list[PageInfo] = []
        self._page_rows: list[PageRow] = []

        self._build_ui()

    # ---- UI construction --------------------------------------------------

    def _build_ui(self):
        # -- Row 0: PDF selection
        row0 = ctk.CTkFrame(self, fg_color="transparent")
        row0.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(row0, text="PDF文件:").pack(side="left")
        self.lbl_pdf = ctk.CTkLabel(row0, text="（未选择）", fg_color="#e8e8e8",
                                     corner_radius=4, width=500, anchor="w")
        self.lbl_pdf.pack(side="left", padx=(8, 8), fill="x", expand=True)
        ctk.CTkButton(row0, text="浏览...", width=80,
                       command=self._browse_pdf).pack(side="right")

        # -- Row 1: Keywords + analyze button
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row1, text="图号标签:").pack(side="left", padx=(0, 4))
        self.entry_kw_dn = ctk.CTkEntry(row1, width=100, placeholder_text="图号")
        self.entry_kw_dn.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(row1, text="图纸名称标签:").pack(side="left", padx=(0, 4))
        self.entry_kw_name = ctk.CTkEntry(row1, width=140, placeholder_text="图纸名称")
        self.entry_kw_name.pack(side="left", padx=(0, 16))

        self.btn_analyze = ctk.CTkButton(row1, text="开始分析", width=100,
                                          command=self._start_analysis)
        self.btn_analyze.pack(side="left")

        self.progress = ctk.CTkProgressBar(row1, width=160, mode="indeterminate")
        self.lbl_status = ctk.CTkLabel(row1, text="", width=120, anchor="w")

        # -- Row 2: Header for page table
        row2 = ctk.CTkFrame(self, fg_color="#d0d0d0", height=28)
        row2.pack(fill="x", padx=12, pady=(8, 0))
        row2.pack_propagate(False)

        ctk.CTkLabel(row2, text="序号", width=50, font=ctk.CTkFont(weight="bold"),
                      anchor="center").pack(side="left", padx=6)
        ctk.CTkLabel(row2, text="图号", width=120, font=ctk.CTkFont(weight="bold"),
                      anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(row2, text="图纸名称", width=260, font=ctk.CTkFont(weight="bold"),
                      anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(row2, text="输出文件名", font=ctk.CTkFont(weight="bold"),
                      anchor="w").pack(side="left", padx=4, fill="x", expand=True)

        # -- Row 3: Scrollable page table
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=4)

        # -- Row 4: Cover checkbox + output dir + split button
        row4 = ctk.CTkFrame(self, fg_color="transparent")
        row4.pack(fill="x", padx=12, pady=(8, 12))

        ctk.CTkLabel(row4, text="输出目录:").pack(side="left")
        self.lbl_outdir = ctk.CTkLabel(row4, text=str(Path.home() / "Desktop"),
                                        width=300, anchor="w", fg_color="#e8e8e8",
                                        corner_radius=4)
        self.lbl_outdir.pack(side="left", padx=(6, 6), fill="x", expand=True)
        ctk.CTkButton(row4, text="选择目录", width=80,
                       command=self._browse_outdir).pack(side="left", padx=(0, 12))

        self.btn_split = ctk.CTkButton(row4, text="拆分!", width=100,
                                        fg_color="#d04040", hover_color="#a03030",
                                        command=self._start_split,
                                        state="disabled")
        self.btn_split.pack(side="right")

        self._add_footer()

    def _add_footer(self):
        """Dark green credit line at the bottom."""
        ctk.CTkLabel(
            self,
            text="Mega_HUGO",
            font=ctk.CTkFont(size=10),
            text_color="#2d6a2d",
        ).pack(side="bottom", pady=(0, 4))

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="选择PDF图纸文件",
            filetypes=[("PDF文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if path:
            self._pdf_path = path
            self.lbl_pdf.configure(text=path)
            self.btn_analyze.configure(state="normal")

    def _browse_outdir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.lbl_outdir.configure(text=path)

    def _start_analysis(self):
        if not self._pdf_path:
            messagebox.showwarning("提示", "请先选择PDF文件。")
            return

        self.btn_analyze.configure(state="disabled")
        self.btn_split.configure(state="disabled")
        self.progress.pack(side="right", padx=(8, 4))
        self.lbl_status.pack(side="right", padx=4)
        self.lbl_status.configure(text="分析中...")
        self.progress.start()

        kw_dn = self.entry_kw_dn.get().strip() or "图号"
        kw_name = self.entry_kw_name.get().strip() or "图纸名称"

        threading.Thread(target=self._do_analysis, args=(kw_dn, kw_name),
                         daemon=True).start()

    def _do_analysis(self, kw_dn: str, kw_name: str):
        try:
            from ..core.pdf_processor import get_page_count
            page_count = get_page_count(self._pdf_path)
            page_infos: list[PageInfo] = []

            for i in range(page_count):
                is_cover = (i == 0)
                info = analyze_page(
                    self._pdf_path, i,
                    dn_keyword=kw_dn,
                    name_keyword=kw_name,
                    is_cover=is_cover,
                )
                page_infos.append(info)

            self._page_infos = page_infos
            self.after(0, self._update_table)
            self.after(0, lambda: self.lbl_status.configure(text=f"完成，共 {page_count} 页"))
        except Exception as e:
            logger.exception("Analysis failed")
            self.after(0, lambda: messagebox.showerror("错误", f"分析失败：{e}"))
        finally:
            self.after(0, self.progress.stop)
            self.after(0, self.progress.pack_forget)
            self.after(0, lambda: self.btn_analyze.configure(state="normal"))
            self.after(0, lambda: self.btn_split.configure(state="normal"))

    def _update_table(self):
        for row in self._page_rows:
            row.destroy()
        self._page_rows.clear()

        for info in self._page_infos:
            row = PageRow(self.scroll_frame, info.index + 1)
            row.set_values(info.drawing_number, info.drawing_name)
            row.bind_edit_callback()
            row.pack(fill="x", pady=1)
            self._page_rows.append(row)

    def _start_split(self):
        if not self._page_rows:
            return

        out_dir = self.lbl_outdir.cget("text")
        if not out_dir:
            messagebox.showwarning("提示", "请选择输出目录。")
            return

        self.btn_split.configure(state="disabled")
        self.lbl_status.configure(text="拆分中...")
        self.progress.pack(side="right", padx=(8, 4))
        self.lbl_status.pack(side="right", padx=4)
        self.progress.start()

        rows_data = [(r.page_num, r.get_values()) for r in self._page_rows]
        threading.Thread(target=self._do_split, args=(rows_data, out_dir),
                         daemon=True).start()

    def _do_split(self, rows_data: list, out_dir: str):
        try:
            import shutil
            from ..core.pdf_processor import save_single_page_pdf

            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)

            for page_num, (dn, name) in rows_data:
                dn_safe = sanitize_filename_part(dn or "无图号")
                name_safe = sanitize_filename_part(name or "无图名")
                fname = f"{page_num}_{dn_safe}_{name_safe}.pdf"
                save_single_page_pdf(self._pdf_path, str(out / fname), page_num - 1)

            count = len(rows_data)
            self.after(0, lambda: messagebox.showinfo(
                "完成", f"已拆分 {count} 个文件到：\n{out}"))
            self.after(0, lambda: self.lbl_status.configure(text=f"已输出 {count} 个文件"))
        except Exception as e:
            logger.exception("Split failed")
            self.after(0, lambda: messagebox.showerror("错误", f"拆分失败：{e}"))
        finally:
            self.after(0, self.progress.stop)
            self.after(0, self.progress.pack_forget)
            self.after(0, lambda: self.btn_split.configure(state="normal"))


def run():
    app = App()
    app.mainloop()
