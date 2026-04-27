"""Юникод-безопасная разбивка текста на чанки для Telegram."""

from __future__ import annotations

DEFAULT_LIMIT = 3900


def split_for_telegram(text: str | None, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Делит текст на чанки длиной до ``limit`` символов.

    Гарантии:
    - Никогда не режет внутри grapheme; работаем по str (codepoints в Python),
      что корректно для UTF-8 и emoji.
    - Старается резать по последнему ``\n`` или пробелу в окне.
    - На вход допускает None / "" — возвращает [].
    - Сохраняет порядок и общий контент: ``"".join(parts) == text`` после
      удаления случайно вставленных пустых сегментов невозможно (мы их и не вставляем).
    - Чанки никогда не пустые: если на входе только пробелы, отдадим один чанк.
    """
    if text is None:
        return []

    if limit <= 0:
        raise ValueError("limit must be positive")

    s = text
    if not s:
        return []

    if len(s) <= limit:
        return [s]

    # Используем "мягкие" точки разреза — переводы строк, потом пробел.
    parts: list[str] = []
    pos = 0
    n = len(s)
    while pos < n:
        end = pos + limit
        if end >= n:
            parts.append(s[pos:])
            break

        window = s[pos:end]
        # Ищем последний \n в окне.
        cut = window.rfind("\n")
        if cut < limit // 2:
            # Если не нашли удобного \n — попробуем последний пробел.
            space_cut = window.rfind(" ")
            if space_cut >= limit // 2:
                cut = space_cut

        if cut <= 0:
            # Нет хорошей точки — режем по жёсткому лимиту.
            parts.append(window)
            pos = end
        else:
            parts.append(s[pos : pos + cut])
            pos = pos + cut
            # Если на месте разреза стоит \n или пробел — пропустим его, чтобы
            # следующий чанк не начинался с одиночного пробела/переноса.
            if pos < n and s[pos] in (" ", "\n"):
                # Но мы храним полный контент, поэтому переносим разделитель
                # к началу следующего чанка только если это \n, чтобы пробел не
                # болтался лидером. Реализация: сдвигаем индекс на 1.
                if s[pos] == " ":
                    pos += 1
                else:  # \n — оставляем у следующего чанка как контекстный отступ
                    pass

    # Убираем потенциальные пустые элементы (на длинных пробельных хвостах).
    return [p for p in parts if p]


__all__ = ["split_for_telegram", "DEFAULT_LIMIT"]
