"""The four post-optional-repo UI tweaks (dogfooding feedback):
1. switcher links to the full Add Product form (no inline org/repo quick-add)
2. no stale mockup number badges in the nav
3. 'Research this site' greys out while researching
4. the Inbox Refresh icon is sized and spins while refreshing
"""
from pmqs.web.render import _load_template


def _tpl():
    return _load_template(None)


# 1 — switcher (also covered end-to-end in test_product_switcher_ui)
def test_switcher_inline_quickadd_is_gone():
    t = _tpl()
    assert 'class="ps-add-form"' not in t
    assert 'href="/products/new"' in t  # links to the full form instead


# 2 — nav badges: the hardcoded mockup numbers are gone
def test_nav_has_no_stale_number_badges():
    t = _tpl()
    assert '<div class="nav-item active" data-nav="inbox">Inbox</div>' in t  # no "5"
    assert '<span class="nav-badge" id="outcomes-badge"></span>' in t  # emptied, no "7"


# 3 — research button greys out (JS already sets disabled; this makes it visible)
def test_research_button_has_disabled_styling():
    t = _tpl()
    assert ".set-btn:disabled" in t


# 4 — refresh icon is sized and can spin
def test_refresh_icon_has_size_and_spin_animation():
    t = _tpl()
    assert "@keyframes pmqs-spin" in t
    assert ".refresh-ico.spinning" in t
