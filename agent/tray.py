def run_tray(on_open, on_stop, on_exit):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None

    def _image():
        img = Image.new("RGB", (64, 64), (30, 30, 30))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 56, 56), fill=(0, 200, 100))
        return img

    menu = pystray.Menu(
        pystray.MenuItem("Открыть", lambda icon, item: on_open(), default=True),
        pystray.MenuItem("Остановить", lambda icon, item: on_stop()),
        pystray.MenuItem("Выход", lambda icon, item: on_exit()),
    )
    return pystray.Icon("5agent", _image(), "5agent", menu)
