# Klan Yönetim Sistemi

Tek yönetici (klan lideri) kullanımına yönelik oyun klan yönetim web uygulaması.

## Özellikler
- Yöneticiye özel güvenli oturum açma ve ilk kurulum (`/setup`, `/login`)
- Yapılandırılabilir oyuncu profili ve zaman serisi gelişim takibi
- Ekran görüntüsünden RapidOCR ile düello puanı çekme ve düzenlenebilir onay akışı
- Dinamik minimum günlük puan limiti yönetimi ve anlık limit değerlendirmesi

## Kurulum ve Çalıştırma (`uv` + Python 3.12)

```powershell
uv sync --python 3.12
uv run python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

## Ortam Değişkenleri
- `CLAN_DB_PATH`: SQLite veritabanı dosya yolu (varsayılan: `data/clan.db`)
- `CLAN_UPLOAD_DIR`: Ekran görüntüsü yükleme klasörü (varsayılan: `data/uploads/screenshots`)
- `CLAN_STATIC_DIR`: Statik SPA dosyaları klasörü (varsayılan: `app/static`)
- `CLAN_SESSION_TTL_HOURS`: Yönetici oturum süresi saat cinsinden (varsayılan: `168`)
- `CLAN_ADMIN_USERNAME` / `CLAN_ADMIN_PASSWORD`: İsteğe bağlı başlangıç yöneticisi (yalnızca `admin_users` boşsa uygulanır)
- `CLAN_COOKIE_SECURE`: `true`/`false` (yerel HTTP için varsayılan `false`)

## Testler

```powershell
uv run pytest tests/unit tests/integration -v
```
