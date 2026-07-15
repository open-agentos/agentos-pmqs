# web/ holds render logic and the app's HTML template.
#
# templates/app.html is production code: render.py splices real data into it at
# request time via anchored regex. Its class names and HTML comment sentinels are
# a load-bearing API — read TEMPLATE-CONTRACT.md before editing its markup.
