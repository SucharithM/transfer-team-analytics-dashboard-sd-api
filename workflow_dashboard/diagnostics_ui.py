"""Explicit, local preview and clipboard sharing of immutable safe reports."""


def open_preview(root, session):
    import tkinter as tk
    from tkinter import ttk

    reports = session.reports()
    if not reports:
        return
    window = tk.Toplevel(root)
    window.title('Error Logs')
    window.geometry('820x560')
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Review these technical diagnostics, then copy them into your support message.').pack(anchor='w')
    selection = ttk.Combobox(frame, state='readonly', values=[f'Attempt {index + 1} · {identifier[:8]}' for index, (identifier, _) in enumerate(reports)])
    selection.pack(fill='x', pady=8)
    selection.current(0)
    body = ttk.Frame(frame)
    body.pack(fill='both', expand=True)
    scrollbar = ttk.Scrollbar(body, orient='vertical')
    text = tk.Text(body, wrap='word', yscrollcommand=scrollbar.set, takefocus=True)
    text.pack(side='left', fill='both', expand=True)
    scrollbar.configure(command=text.yview)
    scrollbar.pack(side='right', fill='y')
    notice = tk.StringVar(value='')

    def show(event=None):
        text.configure(state='normal')
        text.delete('1.0', 'end')
        text.insert('1.0', reports[selection.current()][1])
        text.configure(state='disabled')
        notice.set('')

    def copy():
        try:
            # Copy the immutable validated snapshot, never arbitrary widget text.
            root.clipboard_clear()
            root.clipboard_append(reports[selection.current()][1])
            session.record_report_issue(reports[selection.current()][0], 'clipboard.copy.done')
            notice.set('Logs copied. Paste them into your support message.')
        except Exception as error:
            session.record_report_issue(reports[selection.current()][0], 'clipboard.copy.failed', error=error)
            notice.set('Could not copy logs. Select the report text and copy it manually.')

    selection.bind('<<ComboboxSelected>>', show)
    show()
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=(12, 4))
    ttk.Button(buttons, text='Copy Logs', command=copy).pack(side='left')
    ttk.Button(buttons, text='Close', command=window.destroy).pack(side='right')
    ttk.Label(frame, textvariable=notice, wraplength=760).pack(anchor='w')
    return window
