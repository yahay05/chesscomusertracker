# Chess.com User Tracker

A real-time dashboard for tracking Chess.com users' online status and stats. Built with Python, Flask, Socket.IO, and SQLite.

---

## Features

- Real-time status updates (online, offline, playing, etc.)
- Tracks Chess.com user stats (best rating, country, Puzzle Rush score)
- User avatars and Chess titles
- API URL notifications when status changes
- Add/remove users dynamically from the dashboard
- User login with credentials stored in environment variables
- Clean, responsive UI built with Tailwind CSS

---

## Requirements

- Python 3.10+
- Flask
- Flask-SocketIO
- Requests
- SQLite3
- (Optional) Gunicorn or other WSGI server for production

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Setup

1. Clone the repository:

```bash
git clone <repo_url>
cd chess-user-tracker
```

2. Create a `.env` file in the root directory:

```env
FLASK_APP_SECRET=supersecretkey
ADMIN_USERNAME=admin
ADMIN_PASSWORD=password123
```

3. Initialize the database:

```bash
python app.py
```

This will create `app.db` and seed the admin user from the environment variables.

---

## Running the App

For development:

```bash
python app.py
```

The app will be accessible at `http://127.0.0.1:5000`.

---

## Usage

1. Login with the admin credentials from your `.env` file.
2. Add Chess.com usernames to track.
3. Watch the dashboard for real-time status updates.
4. Configure API URLs for notifications if needed.

---

## Environment Variables

- `FLASK_APP_SECRET` — Flask secret key
- `ADMIN_USERNAME` — Username for the admin login
- `ADMIN_PASSWORD` — Password for the admin login

---

## Tech Stack

- **Backend:** Python, Flask, Flask-SocketIO
- **Database:** SQLite
- **Frontend:** HTML, Tailwind CSS, JavaScript
- **API Integration:** Chess.com public API

---

## License

MIT License

---

## Screenshots

_Include screenshots of the dashboard here if desired._
