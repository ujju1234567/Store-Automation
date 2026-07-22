# Streamlit Community Cloud deployment

This app requires Python 3.11 because PaddlePaddle 3.3.1 does not publish a compatible wheel for Python 3.14.

Before rebooting the app:

1. Open the app in Streamlit Community Cloud.
2. Open **Manage app** and **Settings** (or the app creation **Advanced settings** dialog).
3. Set **Python version** to **3.11**.
4. Save the settings.
5. Reboot or rebuild the app.

The repository includes `runtime.txt` as a local/runtime hint, but the Streamlit Cloud Python-version dropdown is authoritative for the current builder.

The app entry point is `ui.py` and dependencies are in `requirements.txt`.
