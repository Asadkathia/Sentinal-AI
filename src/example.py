def risky(a, b, c, d, e, f):
    TODO = "replace before release"
    try:
        x = a + b
        if x > 0:
            if c:
                if d:
                    if e:
                        if f:
                            return x
        return "fallback"
    except Exception:
        pass
    return None


def duplicate():
    val = 1
    val = 1
    val = 1
    return val
