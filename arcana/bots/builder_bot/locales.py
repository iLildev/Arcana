"""User-facing translations for the Builder Bot.

Translations are stored as a flat ``{key: {lang: text}}`` dict so they are
easy to grep, easy to diff in PRs, and trivial to add new languages to —
just add a new column for the new language code.

Keep the keys descriptive (``phone_prompt_intro`` rather than ``msg_3``)
and group related strings together. Strings may use ``str.format`` style
placeholders (``{balance}``, ``{lang_name}``); the :func:`t` helper passes
``**kwargs`` straight through.

Adding a new language
---------------------
1. Add its code + display name to :data:`LANGUAGES`.
2. Provide a translation for **every** key in :data:`TRANSLATIONS`.
   (CI catches missing keys by importing this module — see
   ``tests/test_locales.py``.)
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Supported languages.
# ─────────────────────────────────────────────────────────────────────────────

# Mapping of ISO 639-1 code → human display name shown in the /lang menu.
LANGUAGES: dict[str, str] = {
    "ar": "🇸🇦 العربية",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "ru": "🇷🇺 Русский",
    "tr": "🇹🇷 Türkçe",
}

# Default language used when the user has not picked one yet.
# English is the primary platform language; Arabic and the other locales
# remain first-class — users can switch any time with /lang.
DEFAULT_LANG: str = "en"


def normalize_lang(code: str | None) -> str:
    """Return a supported language code, falling back to the default."""
    if not code:
        return DEFAULT_LANG
    code = code.strip().lower().split("-")[0]
    return code if code in LANGUAGES else DEFAULT_LANG


# ─────────────────────────────────────────────────────────────────────────────
# Translation table.
#
# Every key MUST be present in every language. Use ``\n`` for line breaks;
# Telegram HTML is enabled at send-time so <b>, <i>, <code> all work.
# ─────────────────────────────────────────────────────────────────────────────

TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── /start welcome ───────────────────────────────────────────────────
    "start_welcome": {
        "ar": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "مساعدك الذكيّ لبناء بوتات Telegram من خلال محادثة عاديّة.\n\n"
            "👤 الحساب: <b>{role}</b>\n"
            "📱 الحالة: {verified}\n"
            "💎 الرصيد: <b>{balance}</b> كرستالة{exempt}\n"
            "💰 التسعير: 1 كرستالة لكلّ <b>{rate}</b> توكن\n\n"
            "اكتب طلبك مباشرةً وسأبني / أُعدّل / أُصحّح بنفسي داخل بيئة معزولة "
            "خاصّة بك.\n\n"
            "📚 اكتب /help لعرض دليل الاستخدام الكامل."
        ),
        "en": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "Your AI partner for building Telegram bots through plain conversation.\n\n"
            "👤 Account: <b>{role}</b>\n"
            "📱 Status: {verified}\n"
            "💎 Balance: <b>{balance}</b> crystals{exempt}\n"
            "💰 Pricing: 1 crystal per <b>{rate}</b> tokens\n\n"
            "Just type your request — I'll write, edit, and debug the code "
            "inside your private sandbox.\n\n"
            "📚 Type /help for the full user guide."
        ),
        "fr": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "Votre partenaire IA pour créer des bots Telegram en langage naturel.\n\n"
            "👤 Compte : <b>{role}</b>\n"
            "📱 Statut : {verified}\n"
            "💎 Solde : <b>{balance}</b> cristaux{exempt}\n"
            "💰 Tarif : 1 cristal pour <b>{rate}</b> tokens\n\n"
            "Décrivez simplement votre besoin — j'écris, modifie et débogue "
            "le code dans votre bac à sable privé.\n\n"
            "📚 Tapez /help pour le guide complet."
        ),
        "es": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "Tu compañero IA para construir bots de Telegram conversando.\n\n"
            "👤 Cuenta: <b>{role}</b>\n"
            "📱 Estado: {verified}\n"
            "💎 Saldo: <b>{balance}</b> cristales{exempt}\n"
            "💰 Precio: 1 cristal por cada <b>{rate}</b> tokens\n\n"
            "Solo escribe tu petición — yo escribo, edito y depuro el código "
            "dentro de tu sandbox privado.\n\n"
            "📚 Escribe /help para ver la guía completa."
        ),
        "ru": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "Ваш ИИ-партнёр для создания Telegram-ботов в обычном диалоге.\n\n"
            "👤 Аккаунт: <b>{role}</b>\n"
            "📱 Статус: {verified}\n"
            "💎 Баланс: <b>{balance}</b> кристаллов{exempt}\n"
            "💰 Тариф: 1 кристалл за <b>{rate}</b> токенов\n\n"
            "Просто опишите задачу — я напишу, изменю и отлажу код в вашей "
            "изолированной песочнице.\n\n"
            "📚 Введите /help для полного руководства."
        ),
        "tr": (
            "🤖 <b>Arcana — Builder Agent</b>\n"
            "Doğal sohbetle Telegram botu inşa etmek için yapay zekâ ortağınız.\n\n"
            "👤 Hesap: <b>{role}</b>\n"
            "📱 Durum: {verified}\n"
            "💎 Bakiye: <b>{balance}</b> kristal{exempt}\n"
            "💰 Fiyat: <b>{rate}</b> token başına 1 kristal\n\n"
            "İsteğinizi yazmanız yeterli — kodu özel kum havuzunuzda ben "
            "yazar, düzenler ve hata ayıklarım.\n\n"
            "📚 Tam kullanım kılavuzu için /help yazın."
        ),
    },
    # ── role labels ──────────────────────────────────────────────────────
    "role_admin": {
        "ar": "👑 المالك",
        "en": "👑 Owner",
        "fr": "👑 Propriétaire",
        "es": "👑 Propietario",
        "ru": "👑 Владелец",
        "tr": "👑 Sahip",
    },
    "role_user": {
        "ar": "مستخدم",
        "en": "User",
        "fr": "Utilisateur",
        "es": "Usuario",
        "ru": "Пользователь",
        "tr": "Kullanıcı",
    },
    "status_verified": {
        "ar": "✅ موثّق",
        "en": "✅ Verified",
        "fr": "✅ Vérifié",
        "es": "✅ Verificado",
        "ru": "✅ Подтверждён",
        "tr": "✅ Doğrulandı",
    },
    "status_unverified": {
        "ar": "🔒 غير موثّق — أرسل أي رسالة لبدء التحقّق",
        "en": "🔒 Unverified — send any message to start verification",
        "fr": "🔒 Non vérifié — envoyez un message pour commencer la vérification",
        "es": "🔒 Sin verificar — envía cualquier mensaje para iniciar la verificación",
        "ru": "🔒 Не подтверждён — отправьте сообщение, чтобы начать проверку",
        "tr": "🔒 Doğrulanmadı — başlamak için herhangi bir mesaj gönderin",
    },
    "exempt_marker": {
        "ar": " (معفى)",
        "en": " (exempt)",
        "fr": " (exempté)",
        "es": " (exento)",
        "ru": " (без оплаты)",
        "tr": " (muaf)",
    },
    # ── /help (full user guide) ──────────────────────────────────────────
    "help_full": {
        "ar": (
            "📚 <b>دليل استخدام Arcana</b>\n\n"
            "<b>1. كيف يعمل البوت؟</b>\n"
            "اكتب ما تريد بناءه أو إصلاحه بلغة طبيعية. سأقوم بكتابة الكود، "
            "تشغيل الاختبارات، وإصلاح الأخطاء داخل مساحة عمل خاصّة بك معزولة "
            "تماماً عن باقي المستخدمين.\n\n"
            "<b>2. الفوترة والكرستالات</b>\n"
            "كلّ طلب يستهلك كرستالات بحسب عدد التوكنات المستخدمة. اطّلع على "
            "رصيدك في أيّ وقت بالأمر /balance.\n\n"
            "<b>3. الأوامر العامّة</b>\n"
            "/start — الرسالة الترحيبيّة\n"
            "/help — هذا الدليل\n"
            "/balance — رصيدك من الكرستالات\n"
            "/stats — إحصائيّات جلستك الحاليّة\n"
            "/reset — مسح الذاكرة وتفريغ مساحة العمل\n"
            "/lang — تغيير لغة البوت\n\n"
            "<b>4. إدارة بوتاتك</b>\n"
            "/mybots — قائمة بوتاتك المزروعة\n"
            "/profile &lt;bot_id&gt; — عرض ملفّ بوت\n"
            "/setname &lt;bot_id&gt; &lt;الاسم&gt; — تغيير اسم البوت\n"
            "/setdesc &lt;bot_id&gt; &lt;الوصف&gt; — تغيير الوصف الطويل\n"
            '/setabout &lt;bot_id&gt; &lt;النصّ&gt; — تغيير وصف "عن البوت"\n\n'
            "<b>5. استيراد مشروع جاهز</b>\n"
            "/import &lt;رابط&gt; — استنساخ مشروع من GitHub أو GitLab "
            "إلى مساحة عملك ثمّ تحليله تلقائياً.\n\n"
            "<b>6. الخصوصيّة</b>\n"
            "نخزّن رقم هاتفك مشفّراً (AES-GCM) للتحقّق فقط. يمكنك حذفه بالكامل "
            "في أيّ وقت بالأمر /unlink_phone.\n\n"
            "<b>7. نصائح للحصول على نتائج أفضل</b>\n"
            '• كن واضحاً ومحدّداً (مثلاً: "أنشئ أمر /price يعرض سعر BTC من '
            'Binance" أفضل من "أضف ميزة الأسعار").\n'
            "• قسّم الطلبات الكبيرة إلى خطوات.\n"
            "• راجع التغييرات قبل النشر.\n\n"
            "هل تحتاج للمساعدة؟ تواصل مع فريق الدعم عبر @iLildev."
        ),
        "en": (
            "📚 <b>Arcana User Guide</b>\n\n"
            "<b>1. How it works</b>\n"
            "Describe what you want to build or fix in natural language. "
            "I'll write the code, run tests, and debug failures inside a "
            "private workspace, fully isolated from other users.\n\n"
            "<b>2. Billing & crystals</b>\n"
            "Each request consumes crystals based on token usage. Check your "
            "balance any time with /balance.\n\n"
            "<b>3. General commands</b>\n"
            "/start — Welcome screen\n"
            "/help — This guide\n"
            "/balance — Your crystal balance\n"
            "/stats — Current session statistics\n"
            "/reset — Clear memory and reset workspace\n"
            "/lang — Change bot language\n\n"
            "<b>4. Manage your bots</b>\n"
            "/mybots — List your planted bots\n"
            "/profile &lt;bot_id&gt; — Show a bot's profile\n"
            "/setname &lt;bot_id&gt; &lt;name&gt; — Rename the bot\n"
            "/setdesc &lt;bot_id&gt; &lt;text&gt; — Update long description\n"
            '/setabout &lt;bot_id&gt; &lt;text&gt; — Update the "About" line\n\n'
            "<b>5. Import an existing project</b>\n"
            "/import &lt;url&gt; — Clone a public GitHub or GitLab repo "
            "into your workspace and have me analyze it for you.\n\n"
            "<b>6. Privacy</b>\n"
            "Your phone is stored encrypted (AES-GCM) and used only for "
            "verification. Delete it at any time with /unlink_phone.\n\n"
            "<b>7. Tips for better results</b>\n"
            '• Be specific (e.g. "add a /price command that fetches BTC from '
            'Binance" beats "add price feature").\n'
            "• Break large requests into smaller steps.\n"
            "• Review changes before deploying.\n\n"
            "Need help? Reach out to @iLildev."
        ),
        "fr": (
            "📚 <b>Guide utilisateur Arcana</b>\n\n"
            "<b>1. Fonctionnement</b>\n"
            "Décrivez ce que vous voulez créer ou corriger en langage naturel. "
            "J'écris le code, lance les tests et corrige les erreurs dans un "
            "espace privé, totalement isolé des autres utilisateurs.\n\n"
            "<b>2. Facturation et cristaux</b>\n"
            "Chaque requête consomme des cristaux en fonction des tokens "
            "utilisés. Consultez votre solde à tout moment avec /balance.\n\n"
            "<b>3. Commandes générales</b>\n"
            "/start — Écran d'accueil\n"
            "/help — Ce guide\n"
            "/balance — Votre solde de cristaux\n"
            "/stats — Statistiques de session\n"
            "/reset — Effacer la mémoire et l'espace de travail\n"
            "/lang — Changer la langue\n\n"
            "<b>4. Gérer vos bots</b>\n"
            "/mybots — Liste de vos bots\n"
            "/profile &lt;bot_id&gt; — Profil d'un bot\n"
            "/setname &lt;bot_id&gt; &lt;nom&gt; — Renommer\n"
            "/setdesc &lt;bot_id&gt; &lt;texte&gt; — Description longue\n"
            "/setabout &lt;bot_id&gt; &lt;texte&gt; — Ligne « À propos »\n\n"
            "<b>5. Importer un projet existant</b>\n"
            "/import &lt;url&gt; — Cloner un dépôt public GitHub ou GitLab "
            "dans votre espace puis le faire analyser.\n\n"
            "<b>6. Vie privée</b>\n"
            "Votre numéro est stocké chiffré (AES-GCM) et utilisé uniquement "
            "pour la vérification. Supprimez-le à tout moment avec "
            "/unlink_phone.\n\n"
            "<b>7. Astuces</b>\n"
            "• Soyez précis (« ajoute /price qui récupère BTC sur Binance » "
            "vaut mieux que « ajoute une fonctionnalité prix »).\n"
            "• Découpez les grandes demandes.\n"
            "• Vérifiez les changements avant déploiement.\n\n"
            "Besoin d'aide ? Contactez @iLildev."
        ),
        "es": (
            "📚 <b>Guía de Arcana</b>\n\n"
            "<b>1. Cómo funciona</b>\n"
            "Describe qué quieres construir o arreglar en lenguaje natural. "
            "Yo escribo el código, ejecuto pruebas y depuro errores dentro "
            "de un espacio privado, aislado de los demás usuarios.\n\n"
            "<b>2. Facturación y cristales</b>\n"
            "Cada petición consume cristales según los tokens usados. "
            "Consulta tu saldo en cualquier momento con /balance.\n\n"
            "<b>3. Comandos generales</b>\n"
            "/start — Pantalla de bienvenida\n"
            "/help — Esta guía\n"
            "/balance — Tu saldo de cristales\n"
            "/stats — Estadísticas de la sesión\n"
            "/reset — Borrar memoria y espacio de trabajo\n"
            "/lang — Cambiar idioma\n\n"
            "<b>4. Gestiona tus bots</b>\n"
            "/mybots — Lista de tus bots\n"
            "/profile &lt;bot_id&gt; — Perfil de un bot\n"
            "/setname &lt;bot_id&gt; &lt;nombre&gt; — Renombrar\n"
            "/setdesc &lt;bot_id&gt; &lt;texto&gt; — Descripción larga\n"
            '/setabout &lt;bot_id&gt; &lt;texto&gt; — Línea "Acerca de"\n\n'
            "<b>5. Importar un proyecto existente</b>\n"
            "/import &lt;url&gt; — Clona un repo público de GitHub o GitLab "
            "en tu workspace y haz que lo analice por ti.\n\n"
            "<b>6. Privacidad</b>\n"
            "Tu número se guarda cifrado (AES-GCM) y se usa solo para "
            "verificación. Elimínalo en cualquier momento con /unlink_phone.\n\n"
            "<b>7. Consejos</b>\n"
            '• Sé específico ("añade /price que obtenga BTC de Binance" es '
            'mejor que "añade función de precios").\n'
            "• Divide peticiones grandes.\n"
            "• Revisa los cambios antes de desplegar.\n\n"
            "¿Necesitas ayuda? Contacta @iLildev."
        ),
        "ru": (
            "📚 <b>Руководство Arcana</b>\n\n"
            "<b>1. Как это работает</b>\n"
            "Опишите, что нужно создать или исправить, обычным языком. "
            "Я пишу код, запускаю тесты и исправляю ошибки в личной "
            "песочнице, полностью изолированной от других пользователей.\n\n"
            "<b>2. Оплата и кристаллы</b>\n"
            "Каждый запрос тратит кристаллы пропорционально количеству "
            "токенов. Проверить баланс — /balance.\n\n"
            "<b>3. Основные команды</b>\n"
            "/start — Приветствие\n"
            "/help — Это руководство\n"
            "/balance — Ваш баланс кристаллов\n"
            "/stats — Статистика сессии\n"
            "/reset — Очистить память и рабочее пространство\n"
            "/lang — Сменить язык\n\n"
            "<b>4. Управление ботами</b>\n"
            "/mybots — Список ваших ботов\n"
            "/profile &lt;bot_id&gt; — Профиль бота\n"
            "/setname &lt;bot_id&gt; &lt;имя&gt; — Переименовать\n"
            "/setdesc &lt;bot_id&gt; &lt;текст&gt; — Длинное описание\n"
            '/setabout &lt;bot_id&gt; &lt;текст&gt; — Строка "О боте"\n\n'
            "<b>5. Импорт готового проекта</b>\n"
            "/import &lt;url&gt; — клонировать публичный репозиторий GitHub "
            "или GitLab в рабочее пространство и попросить меня проанализировать его.\n\n"
            "<b>6. Приватность</b>\n"
            "Ваш номер хранится в зашифрованном виде (AES-GCM) и используется "
            "только для проверки. Удалить его — /unlink_phone.\n\n"
            "<b>7. Советы</b>\n"
            '• Будьте конкретны ("добавь /price, который берёт BTC с '
            'Binance" лучше, чем "добавь функцию цен").\n'
            "• Разбивайте крупные задачи на шаги.\n"
            "• Проверяйте изменения перед публикацией.\n\n"
            "Нужна помощь? Напишите @iLildev."
        ),
        "tr": (
            "📚 <b>Arcana Kullanım Kılavuzu</b>\n\n"
            "<b>1. Nasıl çalışır?</b>\n"
            "Yapmak veya düzeltmek istediğinizi doğal dilde anlatın. Kodu "
            "yazar, testleri çalıştırır ve hataları diğer kullanıcılardan "
            "tamamen izole bir özel alanda ayıklarım.\n\n"
            "<b>2. Faturalandırma ve kristaller</b>\n"
            "Her istek, kullanılan token sayısına göre kristal tüketir. "
            "Bakiyenizi /balance ile görebilirsiniz.\n\n"
            "<b>3. Genel komutlar</b>\n"
            "/start — Karşılama ekranı\n"
            "/help — Bu kılavuz\n"
            "/balance — Kristal bakiyeniz\n"
            "/stats — Oturum istatistikleri\n"
            "/reset — Belleği ve çalışma alanını temizle\n"
            "/lang — Dili değiştir\n\n"
            "<b>4. Botlarınızı yönetin</b>\n"
            "/mybots — Botlarınızın listesi\n"
            "/profile &lt;bot_id&gt; — Bot profili\n"
            "/setname &lt;bot_id&gt; &lt;ad&gt; — Yeniden adlandır\n"
            "/setdesc &lt;bot_id&gt; &lt;metin&gt; — Uzun açıklama\n"
            '/setabout &lt;bot_id&gt; &lt;metin&gt; — "Hakkında" satırı\n\n'
            "<b>5. Mevcut bir projeyi içe aktar</b>\n"
            "/import &lt;url&gt; — Herkese açık bir GitHub veya GitLab deposunu "
            "çalışma alanınıza klonlayıp benim için analiz ettirin.\n\n"
            "<b>6. Gizlilik</b>\n"
            "Telefon numaranız şifreli (AES-GCM) saklanır ve yalnızca "
            "doğrulama için kullanılır. Dilediğiniz zaman /unlink_phone ile "
            "silebilirsiniz.\n\n"
            "<b>7. Daha iyi sonuçlar için ipuçları</b>\n"
            '• Net olun ("Binance\'tan BTC fiyatı çeken /price komutu ekle" '
            'ifadesi "fiyat özelliği ekle"den daha iyidir).\n'
            "• Büyük istekleri parçalara bölün.\n"
            "• Yayına almadan önce değişiklikleri inceleyin.\n\n"
            "Yardıma mı ihtiyacınız var? @iLildev ile iletişime geçin."
        ),
    },
    # ── /balance, /reset, /stats ─────────────────────────────────────────
    "balance_reply": {
        "ar": "💎 رصيدك: <b>{balance}</b> كرستالة",
        "en": "💎 Your balance: <b>{balance}</b> crystals",
        "fr": "💎 Votre solde : <b>{balance}</b> cristaux",
        "es": "💎 Tu saldo: <b>{balance}</b> cristales",
        "ru": "💎 Ваш баланс: <b>{balance}</b> кристаллов",
        "tr": "💎 Bakiyeniz: <b>{balance}</b> kristal",
    },
    "reset_done": {
        "ar": "🧹 تمّ مسح الذاكرة وتفريغ مساحة العمل بنجاح.",
        "en": "🧹 Memory cleared and workspace reset.",
        "fr": "🧹 Mémoire effacée et espace de travail réinitialisé.",
        "es": "🧹 Memoria borrada y espacio de trabajo restablecido.",
        "ru": "🧹 Память очищена, рабочее пространство сброшено.",
        "tr": "🧹 Bellek temizlendi ve çalışma alanı sıfırlandı.",
    },
    "stats_template": {
        "ar": (
            "📊 <b>إحصائيّات جلستك</b>\n"
            "  • الأدوار: <b>{turns}</b>\n"
            "  • التوكنات: <b>{input_tokens}</b> دخل + <b>{output_tokens}</b> خرج\n"
            "  • المكافئ التقريبيّ: <b>~{crystals}</b> كرستالة"
        ),
        "en": (
            "📊 <b>Session statistics</b>\n"
            "  • Turns: <b>{turns}</b>\n"
            "  • Tokens: <b>{input_tokens}</b> in + <b>{output_tokens}</b> out\n"
            "  • Approx. cost: <b>~{crystals}</b> crystals"
        ),
        "fr": (
            "📊 <b>Statistiques de session</b>\n"
            "  • Échanges : <b>{turns}</b>\n"
            "  • Tokens : <b>{input_tokens}</b> entrée + <b>{output_tokens}</b> sortie\n"
            "  • Coût approx. : <b>~{crystals}</b> cristaux"
        ),
        "es": (
            "📊 <b>Estadísticas de sesión</b>\n"
            "  • Turnos: <b>{turns}</b>\n"
            "  • Tokens: <b>{input_tokens}</b> entrada + <b>{output_tokens}</b> salida\n"
            "  • Coste aprox.: <b>~{crystals}</b> cristales"
        ),
        "ru": (
            "📊 <b>Статистика сессии</b>\n"
            "  • Ходов: <b>{turns}</b>\n"
            "  • Токенов: <b>{input_tokens}</b> вх. + <b>{output_tokens}</b> исх.\n"
            "  • Примерная стоимость: <b>~{crystals}</b> кристаллов"
        ),
        "tr": (
            "📊 <b>Oturum istatistikleri</b>\n"
            "  • Tur sayısı: <b>{turns}</b>\n"
            "  • Token: <b>{input_tokens}</b> girdi + <b>{output_tokens}</b> çıktı\n"
            "  • Yaklaşık maliyet: <b>~{crystals}</b> kristal"
        ),
    },
    # ── /lang ────────────────────────────────────────────────────────────
    "lang_choose": {
        "ar": "🌐 <b>اختر لغة البوت</b>\nاللغة الحاليّة: <b>{current}</b>",
        "en": "🌐 <b>Choose bot language</b>\nCurrent language: <b>{current}</b>",
        "fr": "🌐 <b>Choisissez la langue du bot</b>\nLangue actuelle : <b>{current}</b>",
        "es": "🌐 <b>Elige el idioma del bot</b>\nIdioma actual: <b>{current}</b>",
        "ru": "🌐 <b>Выберите язык бота</b>\nТекущий язык: <b>{current}</b>",
        "tr": "🌐 <b>Bot dilini seçin</b>\nMevcut dil: <b>{current}</b>",
    },
    "lang_changed": {
        "ar": "✅ تمّ تغيير اللغة إلى <b>{name}</b>.",
        "en": "✅ Language changed to <b>{name}</b>.",
        "fr": "✅ Langue changée en <b>{name}</b>.",
        "es": "✅ Idioma cambiado a <b>{name}</b>.",
        "ru": "✅ Язык изменён на <b>{name}</b>.",
        "tr": "✅ Dil <b>{name}</b> olarak değiştirildi.",
    },
    "lang_invalid": {
        "ar": "⚠️ رمز لغة غير معروف. الرموز المتاحة: <code>{codes}</code>",
        "en": "⚠️ Unknown language code. Available: <code>{codes}</code>",
        "fr": "⚠️ Code de langue inconnu. Disponibles : <code>{codes}</code>",
        "es": "⚠️ Código de idioma desconocido. Disponibles: <code>{codes}</code>",
        "ru": "⚠️ Неизвестный код языка. Доступны: <code>{codes}</code>",
        "tr": "⚠️ Bilinmeyen dil kodu. Mevcut: <code>{codes}</code>",
    },
    # ── Phone verification ───────────────────────────────────────────────
    "phone_share_button": {
        "ar": "📱 شارك رقمي للتحقّق",
        "en": "📱 Share my number to verify",
        "fr": "📱 Partager mon numéro",
        "es": "📱 Compartir mi número",
        "ru": "📱 Поделиться номером",
        "tr": "📱 Numaramı paylaş",
    },
    "phone_prompt": {
        "ar": (
            "🔒 <b>تحقّق سريع قبل البدء</b>\n\n"
            "قبل استخدام Builder Agent، يرجى التحقّق من حسابك عبر مشاركة "
            "رقمك من Telegram.\n\n"
            "<b>لماذا؟</b>\n"
            "• حماية المنصّة من السبام والحسابات الوهميّة.\n"
            "• حدّ عادل للموارد لكلّ مستخدم.\n"
            "• تمكين إدارة بوتاتك لاحقاً عبر BotFather آليّاً.\n\n"
            "اضغط الزرّ بالأسفل. يمكنك حذف بياناتك في أيّ وقت بالأمر "
            "/unlink_phone."
        ),
        "en": (
            "🔒 <b>Quick verification before we start</b>\n\n"
            "Before using Builder Agent, please verify your account by "
            "sharing your Telegram phone number.\n\n"
            "<b>Why?</b>\n"
            "• Protects the platform from spam and fake accounts.\n"
            "• Ensures fair resource limits per user.\n"
            "• Enables BotFather automation for your bots later on.\n\n"
            "Tap the button below. You can erase your data any time with "
            "/unlink_phone."
        ),
        "fr": (
            "🔒 <b>Vérification rapide avant de commencer</b>\n\n"
            "Avant d'utiliser Builder Agent, veuillez vérifier votre compte "
            "en partageant votre numéro Telegram.\n\n"
            "<b>Pourquoi ?</b>\n"
            "• Protection contre le spam et les faux comptes.\n"
            "• Limites de ressources équitables par utilisateur.\n"
            "• Permet l'automatisation BotFather plus tard.\n\n"
            "Appuyez sur le bouton ci-dessous. Vous pouvez effacer vos "
            "données à tout moment avec /unlink_phone."
        ),
        "es": (
            "🔒 <b>Verificación rápida antes de empezar</b>\n\n"
            "Antes de usar Builder Agent, verifica tu cuenta compartiendo tu "
            "número de Telegram.\n\n"
            "<b>¿Por qué?</b>\n"
            "• Protege la plataforma del spam y cuentas falsas.\n"
            "• Garantiza límites justos por usuario.\n"
            "• Habilita la automatización de BotFather más adelante.\n\n"
            "Pulsa el botón. Puedes borrar tus datos en cualquier momento "
            "con /unlink_phone."
        ),
        "ru": (
            "🔒 <b>Быстрая проверка перед началом</b>\n\n"
            "Перед использованием Builder Agent подтвердите аккаунт, "
            "поделившись номером телефона Telegram.\n\n"
            "<b>Зачем?</b>\n"
            "• Защита от спама и фальшивых аккаунтов.\n"
            "• Справедливые лимиты ресурсов для каждого.\n"
            "• Возможность автоматизации BotFather позже.\n\n"
            "Нажмите кнопку ниже. Вы можете удалить данные в любой момент "
            "командой /unlink_phone."
        ),
        "tr": (
            "🔒 <b>Başlamadan önce hızlı doğrulama</b>\n\n"
            "Builder Agent'ı kullanmadan önce, Telegram telefon numaranızı "
            "paylaşarak hesabınızı doğrulayın.\n\n"
            "<b>Neden?</b>\n"
            "• Platformu spam ve sahte hesaplardan korur.\n"
            "• Kullanıcı başına adil kaynak sınırları sağlar.\n"
            "• İlerideki BotFather otomasyonunu mümkün kılar.\n\n"
            "Aşağıdaki düğmeye dokunun. Verilerinizi /unlink_phone ile "
            "istediğiniz zaman silebilirsiniz."
        ),
    },
    "phone_verified_ok": {
        "ar": "✅ <b>تمّ التحقّق بنجاح</b>\n\nيمكنك الآن استخدام Builder Agent. أرسل طلبك متى شئت.",
        "en": "✅ <b>Verification successful</b>\n\nYou can now use Builder "
        "Agent. Send your request whenever you're ready.",
        "fr": "✅ <b>Vérification réussie</b>\n\nVous pouvez maintenant "
        "utiliser Builder Agent. Envoyez votre requête quand vous voulez.",
        "es": "✅ <b>Verificación exitosa</b>\n\nYa puedes usar Builder Agent. "
        "Envía tu petición cuando quieras.",
        "ru": "✅ <b>Проверка пройдена</b>\n\nТеперь вы можете пользоваться "
        "Builder Agent. Отправьте запрос, когда будете готовы.",
        "tr": "✅ <b>Doğrulama başarılı</b>\n\nArtık Builder Agent'ı "
        "kullanabilirsiniz. Hazır olduğunuzda isteğinizi gönderin.",
    },
    "phone_only_own": {
        "ar": "⚠️ يجب مشاركة رقمك أنت، لا رقم شخص آخر. اضغط زرّ المشاركة بدلاً "
        "من إرسال جهة اتصال يدويّاً.",
        "en": "⚠️ You must share your own number, not someone else's. Tap the "
        "share button instead of forwarding a contact.",
        "fr": "⚠️ Vous devez partager votre propre numéro, pas celui d'un "
        "autre. Utilisez le bouton de partage.",
        "es": "⚠️ Debes compartir tu propio número, no el de otra persona. "
        "Usa el botón de compartir.",
        "ru": "⚠️ Нужно поделиться именно своим номером. Нажмите кнопку "
        "вместо ручной пересылки контакта.",
        "tr": "⚠️ Başka birinin değil, kendi numaranızı paylaşmalısınız. "
        "Kişi yönlendirmek yerine paylaş düğmesine dokunun.",
    },
    "phone_dup_error": {
        "ar": "❌ تعذّر التحقّق: {error}\n\nإن كنت قد سجّلت بحساب آخر، استخدم "
        "/unlink_phone هناك أوّلاً.",
        "en": "❌ Verification failed: {error}\n\nIf you registered with "
        "another account, use /unlink_phone there first.",
        "fr": "❌ Échec de la vérification : {error}\n\nSi vous êtes inscrit "
        "avec un autre compte, utilisez /unlink_phone là-bas d'abord.",
        "es": "❌ Verificación fallida: {error}\n\nSi te registraste con otra "
        "cuenta, usa /unlink_phone allí primero.",
        "ru": "❌ Ошибка проверки: {error}\n\nЕсли вы регистрировались под "
        "другой учётной записью, выполните /unlink_phone там.",
        "tr": "❌ Doğrulama başarısız: {error}\n\nBaşka bir hesapla kayıt "
        "olduysanız, önce orada /unlink_phone kullanın.",
    },
    "phone_internal_error": {
        "ar": "❌ خطأ داخليّ أثناء التحقّق: {error}",
        "en": "❌ Internal error during verification: {error}",
        "fr": "❌ Erreur interne lors de la vérification : {error}",
        "es": "❌ Error interno durante la verificación: {error}",
        "ru": "❌ Внутренняя ошибка при проверке: {error}",
        "tr": "❌ Doğrulama sırasında dahili hata: {error}",
    },
    "phone_unlinked": {
        "ar": "🗑️ تمّ حذف رقمك من المنصّة. ستحتاج إلى التحقّق مجدّداً قبل الاستخدام المتقدّم.",
        "en": "🗑️ Your phone number has been removed. You'll need to verify "
        "again before advanced usage.",
        "fr": "🗑️ Votre numéro a été supprimé. Vous devrez vous re-vérifier "
        "pour les fonctions avancées.",
        "es": "🗑️ Tu número fue eliminado. Tendrás que verificarte de nuevo "
        "para usar funciones avanzadas.",
        "ru": "🗑️ Ваш номер удалён. Для расширенного использования потребуется новая проверка.",
        "tr": "🗑️ Numaranız silindi. Gelişmiş kullanım için tekrar doğrulamanız gerekir.",
    },
    "phone_no_record": {
        "ar": "ℹ️ لا يوجد رقم مسجّل لحسابك.",
        "en": "ℹ️ No phone number is linked to your account.",
        "fr": "ℹ️ Aucun numéro n'est associé à votre compte.",
        "es": "ℹ️ No hay número vinculado a tu cuenta.",
        "ru": "ℹ️ К вашему аккаунту не привязан номер.",
        "tr": "ℹ️ Hesabınıza bağlı bir numara yok.",
    },
    # ── /mybots, /profile, /setname, /setdesc, /setabout ─────────────────
    "mybots_empty": {
        "ar": "📭 لا توجد بوتات بعد. استخدم Builder Agent لإنشاء أوّل بوت.",
        "en": "📭 No bots yet. Use Builder Agent to plant your first one.",
        "fr": "📭 Aucun bot pour l'instant. Utilisez Builder Agent pour en créer un.",
        "es": "📭 Aún no tienes bots. Usa Builder Agent para crear el primero.",
        "ru": "📭 Ботов пока нет. Создайте первого через Builder Agent.",
        "tr": "📭 Henüz bot yok. İlk botunuzu Builder Agent ile oluşturun.",
    },
    "mybots_header": {
        "ar": "🤖 <b>بوتاتك:</b>",
        "en": "🤖 <b>Your bots:</b>",
        "fr": "🤖 <b>Vos bots :</b>",
        "es": "🤖 <b>Tus bots:</b>",
        "ru": "🤖 <b>Ваши боты:</b>",
        "tr": "🤖 <b>Botlarınız:</b>",
    },
    "mybots_unnamed": {
        "ar": "(بلا اسم)",
        "en": "(unnamed)",
        "fr": "(sans nom)",
        "es": "(sin nombre)",
        "ru": "(без имени)",
        "tr": "(adsız)",
    },
    "mybots_hint": {
        "ar": "أوامر الإدارة: /profile · /setname · /setdesc · /setabout",
        "en": "Management: /profile · /setname · /setdesc · /setabout",
        "fr": "Gestion : /profile · /setname · /setdesc · /setabout",
        "es": "Gestión: /profile · /setname · /setdesc · /setabout",
        "ru": "Управление: /profile · /setname · /setdesc · /setabout",
        "tr": "Yönetim: /profile · /setname · /setdesc · /setabout",
    },
    "profile_usage": {
        "ar": "الاستخدام: <code>/profile &lt;bot_id&gt;</code>",
        "en": "Usage: <code>/profile &lt;bot_id&gt;</code>",
        "fr": "Usage : <code>/profile &lt;bot_id&gt;</code>",
        "es": "Uso: <code>/profile &lt;bot_id&gt;</code>",
        "ru": "Использование: <code>/profile &lt;bot_id&gt;</code>",
        "tr": "Kullanım: <code>/profile &lt;bot_id&gt;</code>",
    },
    "profile_read_failed": {
        "ar": "❌ تعذّر قراءة الملفّ: {error}",
        "en": "❌ Could not read the profile: {error}",
        "fr": "❌ Impossible de lire le profil : {error}",
        "es": "❌ No se pudo leer el perfil: {error}",
        "ru": "❌ Не удалось прочитать профиль: {error}",
        "tr": "❌ Profil okunamadı: {error}",
    },
    "profile_template": {
        "ar": (
            "🪪 <b>@{username}</b>\n"
            "الاسم: {name}\n"
            "نبذة قصيرة: {about}\n"
            "الوصف: {desc}\n"
            "الأوامر:\n{cmds}"
        ),
        "en": (
            "🪪 <b>@{username}</b>\n"
            "Name: {name}\n"
            "About: {about}\n"
            "Description: {desc}\n"
            "Commands:\n{cmds}"
        ),
        "fr": (
            "🪪 <b>@{username}</b>\n"
            "Nom : {name}\n"
            "À propos : {about}\n"
            "Description : {desc}\n"
            "Commandes :\n{cmds}"
        ),
        "es": (
            "🪪 <b>@{username}</b>\n"
            "Nombre: {name}\n"
            "Acerca de: {about}\n"
            "Descripción: {desc}\n"
            "Comandos:\n{cmds}"
        ),
        "ru": (
            "🪪 <b>@{username}</b>\n"
            "Имя: {name}\n"
            "О боте: {about}\n"
            "Описание: {desc}\n"
            "Команды:\n{cmds}"
        ),
        "tr": (
            "🪪 <b>@{username}</b>\n"
            "Ad: {name}\n"
            "Hakkında: {about}\n"
            "Açıklama: {desc}\n"
            "Komutlar:\n{cmds}"
        ),
    },
    "profile_empty_field": {
        "ar": "(فارغ)",
        "en": "(empty)",
        "fr": "(vide)",
        "es": "(vacío)",
        "ru": "(пусто)",
        "tr": "(boş)",
    },
    "profile_no_commands": {
        "ar": "  (لا يوجد)",
        "en": "  (none)",
        "fr": "  (aucune)",
        "es": "  (ninguno)",
        "ru": "  (нет)",
        "tr": "  (yok)",
    },
    "setname_usage": {
        "ar": "الاستخدام: <code>/setname &lt;bot_id&gt; &lt;الاسم الجديد&gt;</code>",
        "en": "Usage: <code>/setname &lt;bot_id&gt; &lt;new name&gt;</code>",
        "fr": "Usage : <code>/setname &lt;bot_id&gt; &lt;nouveau nom&gt;</code>",
        "es": "Uso: <code>/setname &lt;bot_id&gt; &lt;nuevo nombre&gt;</code>",
        "ru": "Использование: <code>/setname &lt;bot_id&gt; &lt;новое имя&gt;</code>",
        "tr": "Kullanım: <code>/setname &lt;bot_id&gt; &lt;yeni ad&gt;</code>",
    },
    "setdesc_usage": {
        "ar": "الاستخدام: <code>/setdesc &lt;bot_id&gt; &lt;الوصف&gt;</code>",
        "en": "Usage: <code>/setdesc &lt;bot_id&gt; &lt;description&gt;</code>",
        "fr": "Usage : <code>/setdesc &lt;bot_id&gt; &lt;description&gt;</code>",
        "es": "Uso: <code>/setdesc &lt;bot_id&gt; &lt;descripción&gt;</code>",
        "ru": "Использование: <code>/setdesc &lt;bot_id&gt; &lt;описание&gt;</code>",
        "tr": "Kullanım: <code>/setdesc &lt;bot_id&gt; &lt;açıklama&gt;</code>",
    },
    "setabout_usage": {
        "ar": "الاستخدام: <code>/setabout &lt;bot_id&gt; &lt;النصّ&gt;</code>",
        "en": "Usage: <code>/setabout &lt;bot_id&gt; &lt;text&gt;</code>",
        "fr": "Usage : <code>/setabout &lt;bot_id&gt; &lt;texte&gt;</code>",
        "es": "Uso: <code>/setabout &lt;bot_id&gt; &lt;texto&gt;</code>",
        "ru": "Использование: <code>/setabout &lt;bot_id&gt; &lt;текст&gt;</code>",
        "tr": "Kullanım: <code>/setabout &lt;bot_id&gt; &lt;metin&gt;</code>",
    },
    "bot_not_found": {
        "ar": "❌ لم أجد هذا البوت ضمن بوتاتك.",
        "en": "❌ I couldn't find that bot among yours.",
        "fr": "❌ Ce bot n'est pas dans votre liste.",
        "es": "❌ No encontré ese bot entre los tuyos.",
        "ru": "❌ Не нашёл такой бот среди ваших.",
        "tr": "❌ Bu botu listenizde bulamadım.",
    },
    "update_ok": {
        "ar": "✅ تمّ.",
        "en": "✅ Done.",
        "fr": "✅ Fait.",
        "es": "✅ Listo.",
        "ru": "✅ Готово.",
        "tr": "✅ Tamam.",
    },
    "update_warn": {
        "ar": "⚠️ {detail}",
        "en": "⚠️ {detail}",
        "fr": "⚠️ {detail}",
        "es": "⚠️ {detail}",
        "ru": "⚠️ {detail}",
        "tr": "⚠️ {detail}",
    },
    # ── Agent runtime messages ───────────────────────────────────────────
    "agent_thinking": {
        "ar": "🤖 يفكّر…",
        "en": "🤖 Thinking…",
        "fr": "🤖 Réflexion…",
        "es": "🤖 Pensando…",
        "ru": "🤖 Думаю…",
        "tr": "🤖 Düşünüyor…",
    },
    "agent_no_balance": {
        "ar": "🚫 لا يوجد رصيد كافٍ. اشحن محفظتك ثمّ أعد المحاولة.",
        "en": "🚫 Insufficient balance. Top up your wallet and try again.",
        "fr": "🚫 Solde insuffisant. Rechargez votre portefeuille et réessayez.",
        "es": "🚫 Saldo insuficiente. Recarga tu cartera e inténtalo de nuevo.",
        "ru": "🚫 Недостаточно средств. Пополните кошелёк и повторите.",
        "tr": "🚫 Bakiye yetersiz. Cüzdanınızı yükleyip tekrar deneyin.",
    },
    "agent_error": {
        "ar": "❌ خطأ: {kind}: {detail}",
        "en": "❌ Error: {kind}: {detail}",
        "fr": "❌ Erreur : {kind} : {detail}",
        "es": "❌ Error: {kind}: {detail}",
        "ru": "❌ Ошибка: {kind}: {detail}",
        "tr": "❌ Hata: {kind}: {detail}",
    },
    "footer_admin": {
        "ar": "👑 معفى",
        "en": "👑 Exempt",
        "fr": "👑 Exempté",
        "es": "👑 Exento",
        "ru": "👑 Без оплаты",
        "tr": "👑 Muaf",
    },
    "footer_billed": {
        "ar": "💎 -{cost} (متبقّي {balance})",
        "en": "💎 -{cost} (remaining {balance})",
        "fr": "💎 -{cost} (restant {balance})",
        "es": "💎 -{cost} (restante {balance})",
        "ru": "💎 -{cost} (осталось {balance})",
        "tr": "💎 -{cost} (kalan {balance})",
    },
    # ── /broadcast (admin-only) ──────────────────────────────────────────
    "broadcast_usage": {
        "ar": "الاستخدام: <code>/broadcast &lt;الرسالة&gt;</code>",
        "en": "Usage: <code>/broadcast &lt;message&gt;</code>",
        "fr": "Usage : <code>/broadcast &lt;message&gt;</code>",
        "es": "Uso: <code>/broadcast &lt;mensaje&gt;</code>",
        "ru": "Использование: <code>/broadcast &lt;сообщение&gt;</code>",
        "tr": "Kullanım: <code>/broadcast &lt;mesaj&gt;</code>",
    },
    "broadcast_started": {
        "ar": "📣 بدأ البثّ إلى {count} مستخدم…",
        "en": "📣 Broadcast started to {count} users…",
        "fr": "📣 Diffusion lancée vers {count} utilisateurs…",
        "es": "📣 Difusión iniciada a {count} usuarios…",
        "ru": "📣 Рассылка запущена для {count} пользователей…",
        "tr": "📣 Yayın {count} kullanıcıya başlatıldı…",
    },
    "broadcast_done": {
        "ar": "✅ انتهى البثّ — تمّ: {sent} · محظور: {blocked} · فشل: {failed}",
        "en": "✅ Broadcast done — sent: {sent} · blocked: {blocked} · failed: {failed}",
        "fr": "✅ Diffusion terminée — envoyé : {sent} · bloqué : {blocked} · échec : {failed}",
        "es": "✅ Difusión completada — enviado: {sent} · bloqueado: {blocked} · fallido: {failed}",
        "ru": "✅ Рассылка завершена — отправлено: {sent} · заблокировано: {blocked} · ошибок: {failed}",
        "tr": "✅ Yayın tamam — gönderildi: {sent} · engellendi: {blocked} · başarısız: {failed}",
    },
    "broadcast_no_recipients": {
        "ar": "ℹ️ لا يوجد مستلمون مؤهّلون للبثّ.",
        "en": "ℹ️ No eligible recipients to broadcast to.",
        "fr": "ℹ️ Aucun destinataire éligible pour la diffusion.",
        "es": "ℹ️ No hay destinatarios elegibles para la difusión.",
        "ru": "ℹ️ Нет подходящих получателей для рассылки.",
        "tr": "ℹ️ Yayınlanacak uygun alıcı yok.",
    },
    "admin_only": {
        "ar": "🚫 هذا الأمر للمسؤولين فقط.",
        "en": "🚫 This command is admin-only.",
        "fr": "🚫 Cette commande est réservée aux administrateurs.",
        "es": "🚫 Este comando es solo para administradores.",
        "ru": "🚫 Эта команда доступна только администраторам.",
        "tr": "🚫 Bu komut yalnızca yöneticiler içindir.",
    },
    "generic_error": {
        "ar": "⚠️ حدث خطأ غير متوقّع. تمّ تنبيه فريق التشغيل.",
        "en": "⚠️ An unexpected error occurred. Operators have been notified.",
        "fr": "⚠️ Une erreur inattendue s'est produite. Les opérateurs ont été notifiés.",
        "es": "⚠️ Ocurrió un error inesperado. Se notificó a los operadores.",
        "ru": "⚠️ Произошла непредвиденная ошибка. Операторы уведомлены.",
        "tr": "⚠️ Beklenmeyen bir hata oluştu. Operatörler bilgilendirildi.",
    },
    # ── /import (GitHub / GitLab repo import) ────────────────────────────
    "import_usage": {
        "ar": (
            "الاستخدام: <code>/import &lt;رابط&gt;</code>\n"
            "مثال: <code>/import https://github.com/user/repo</code>\n\n"
            "تُقبل المستودعات العامّة من <b>GitHub</b> و <b>GitLab</b> فقط."
        ),
        "en": (
            "Usage: <code>/import &lt;url&gt;</code>\n"
            "Example: <code>/import https://github.com/user/repo</code>\n\n"
            "Only public <b>GitHub</b> and <b>GitLab</b> repos are accepted."
        ),
        "fr": (
            "Usage : <code>/import &lt;url&gt;</code>\n"
            "Exemple : <code>/import https://github.com/user/repo</code>\n\n"
            "Seuls les dépôts publics <b>GitHub</b> et <b>GitLab</b> sont acceptés."
        ),
        "es": (
            "Uso: <code>/import &lt;url&gt;</code>\n"
            "Ejemplo: <code>/import https://github.com/user/repo</code>\n\n"
            "Solo se aceptan repos públicos de <b>GitHub</b> y <b>GitLab</b>."
        ),
        "ru": (
            "Использование: <code>/import &lt;url&gt;</code>\n"
            "Пример: <code>/import https://github.com/user/repo</code>\n\n"
            "Принимаются только публичные репозитории <b>GitHub</b> и <b>GitLab</b>."
        ),
        "tr": (
            "Kullanım: <code>/import &lt;url&gt;</code>\n"
            "Örnek: <code>/import https://github.com/user/repo</code>\n\n"
            "Yalnızca herkese açık <b>GitHub</b> ve <b>GitLab</b> depoları kabul edilir."
        ),
    },
    "import_invalid_url": {
        "ar": "❌ الرابط غير صالح. يجب أن يبدأ بـ <code>https://github.com/</code> أو <code>https://gitlab.com/</code>.",
        "en": "❌ Invalid URL. It must start with <code>https://github.com/</code> or <code>https://gitlab.com/</code>.",
        "fr": "❌ URL invalide. Elle doit commencer par <code>https://github.com/</code> ou <code>https://gitlab.com/</code>.",
        "es": "❌ URL no válida. Debe comenzar por <code>https://github.com/</code> o <code>https://gitlab.com/</code>.",
        "ru": "❌ Недопустимый URL. Должен начинаться с <code>https://github.com/</code> или <code>https://gitlab.com/</code>.",
        "tr": "❌ Geçersiz URL. <code>https://github.com/</code> veya <code>https://gitlab.com/</code> ile başlamalı.",
    },
    "import_started": {
        "ar": "📥 جاري استنساخ <code>{repo}</code> إلى مساحة عملك… سأرسل ملخّصاً عند الانتهاء.",
        "en": "📥 Cloning <code>{repo}</code> into your workspace… I'll send an overview when it's ready.",
        "fr": "📥 Clonage de <code>{repo}</code> dans votre espace… J'enverrai un résumé une fois prêt.",
        "es": "📥 Clonando <code>{repo}</code> en tu workspace… Te enviaré un resumen cuando esté listo.",
        "ru": "📥 Клонирую <code>{repo}</code> в ваше рабочее пространство… Пришлю обзор, когда будет готов.",
        "tr": "📥 <code>{repo}</code> çalışma alanınıza klonlanıyor… Hazır olunca özet göndereceğim.",
    },
}


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Translate *key* into *lang*, falling back to default + then to key.

    Unknown keys return the key itself wrapped in brackets so missing
    translations are obvious in the UI without crashing the bot.
    Placeholder values are passed through ``str.format``.
    """
    lang = normalize_lang(lang)
    bundle = TRANSLATIONS.get(key)
    if bundle is None:
        return f"[missing:{key}]"
    text = bundle.get(lang) or bundle.get(DEFAULT_LANG) or f"[missing:{key}:{lang}]"
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
