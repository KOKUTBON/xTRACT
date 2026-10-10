/**
 * Internationalization (i18n) engine and multilingual dictionaries for the Operator Portal.
 */

export const SUPPORTED_LOCALES = [
  { code: "en", name: "English", flag: "🇬🇧" },
  { code: "it", name: "Italiano", flag: "🇮🇹" },
  { code: "es", name: "Español", flag: "🇪🇸" },
  { code: "fr", name: "Français", flag: "🇫🇷" },
  { code: "de", name: "Deutsch", flag: "🇩🇪" },
];

const DICTIONARIES = {
  en: {
    // Navigation & header
    nav_queue: "Review queue",
    nav_documents: "All documents",
    nav_exceptions: "Exceptions",
    nav_shortcuts: "Keyboard shortcuts",
    nav_theme: "Switch theme",
    nav_settings: "Operator settings",
    search_placeholder: "Search OCR text, values, references, file names",
    search_label: "Search documents",
    stage_filter_all: "All stages",
    stage_filter_label: "Workflow stage",
    export: "Export",
    export_fields_csv: "Field values",
    export_jsonl: "Research dataset",
    export_jsonl_ocr: "Dataset + OCR text",
    export_json: "Validated exports",
    export_menu_label: "Research datasets",
    upload: "Upload",

    // Lists & Panes
    list_queue_title: "Review queue",
    list_queue_eyebrow: "Human in the loop",
    list_documents_title: "All documents",
    list_documents_eyebrow: "Library",
    list_exceptions_title: "Exceptions",
    list_exceptions_eyebrow: "Needs attention",
    list_empty: "No documents found",

    // Workspace
    empty_title: "Drop a document to begin",
    empty_desc: "Text files, PDFs, and scanned images are OCR'd locally, classified, and extracted. Uncertain values wait here for your review.",
    empty_upload_btn: "Upload documents",
    empty_browse_btn: "Browse all",
    empty_scan_title: "Scan",
    empty_scan_desc: "Text layer, PDF, or Tesseract OCR",
    empty_extract_title: "Extract",
    empty_extract_desc: "Taxonomy rules with confidence signals",
    empty_verify_title: "Verify",
    empty_verify_desc: "Side-by-side review, full audit trail",
    view_ocr_text: "OCR text",
    view_original: "Original",
    fields_title: "Extracted fields",
    fields_empty: "No fields were extracted for this document.",
    fields_processing: "Fields appear after extraction.",
    not_found_in_text: "Not found in text",
    was_value: "was “{value}”",

    // Stages
    stage_acquired: "Queued for OCR",
    stage_ocr_executed: "Extracting",
    stage_to_be_verified: "Needs review",
    stage_validated: "Validated",
    stage_protocol_pending: "Registering",
    stage_protocol_registered: "Registered",
    stage_discarded: "Discarded",
    stage_failed: "Failed",

    // Lifecycle
    lifecycle_intake: "Intake",
    lifecycle_ocr: "OCR",
    lifecycle_review: "Review",
    lifecycle_validated: "Validated",
    lifecycle_registering: "Registering",
    lifecycle_registered: "Registered",

    // Reasons
    reason_low_confidence: "Low confidence",
    reason_validation_pattern_mismatch: "Format check failed",
    reason_required_field_missing: "Required value missing",
    reason_manual_policy_review: "Manual review requested",

    // Actions
    action_complete_review: "Complete review",
    action_reopen_review: "Reopen review",
    action_retry_integration: "Retry registration",
    action_request_reprocessing: "Reprocess",
    action_discard_document: "Discard",
    action_cancel: "Cancel",
    action_save: "Save",
    action_close: "Close",
    action_confirm: "Confirm",
    action_resolve: "Resolve",

    // Inspector
    tab_assistant: "Assistant",
    tab_issues: "Issues",
    tab_registry: "Registry",
    tab_jobs: "Jobs",
    tab_audit: "Audit",
    assistant_heading: "Document assistant",
    assistant_source_bounded: "Source-bounded",
    assistant_note: "Answers are grounded only in this document's text, fields, and history — every claim is cited. Decisions stay with you.",
    assistant_prompt_placeholder: "Ask about this document…",
    assistant_ask_btn: "Ask",
    exceptions_heading: "Exceptions",
    registration_heading: "Protocol registration",
    jobs_heading: "Processing jobs",
    audit_heading: "Audit trail",
    audit_immutable: "Immutable",

    // Dialogs
    dialog_upload_title: "Upload documents",
    dialog_upload_eyebrow: "Intake",
    dialog_upload_dropzone: "Drop files here or browse",
    dialog_upload_type: "Document type",
    dialog_upload_auto: "Detect automatically",
    dialog_upload_institution: "Institution",
    dialog_upload_office: "Office",
    dialog_upload_security: "SHA-256 deduplicated · processed on-device",
    dialog_reprocess_title: "Request reprocessing",
    dialog_reprocess_scope_legend: "What should run again?",
    dialog_reprocess_scope_ext: "Metadata extraction",
    dialog_reprocess_scope_ext_sub: "Keeps the current OCR text",
    dialog_reprocess_scope_ocr: "OCR and extraction",
    dialog_reprocess_scope_ocr_sub: "Re-reads the original file from scratch",
    dialog_reprocess_comment: "Comment",
    dialog_reprocess_comment_ph: "Optional — recorded in the audit trail",
    dialog_reprocess_note: "Pending review work on this document is cancelled and recreated by the new run.",
    dialog_settings_title: "Settings",
    dialog_settings_eyebrow: "Operator",
    dialog_settings_name: "Your name",
    dialog_settings_name_meta: "recorded in the audit trail",
    dialog_settings_token: "API token",
    dialog_settings_token_ph: "Only if the server sets XTRACT_API_TOKEN",
    dialog_settings_token_meta: "Kept in session storage only and sent as a Bearer header.",
    dialog_settings_language: "Language",
    dialog_settings_pack: "Domain pack",
    dialog_settings_role: "Assigned role",
    role_admin: "Administrator",
    role_supervisor: "Supervisor",
    role_operator: "Operator",
    role_viewer: "Viewer (Read-only)",
    role_auditor: "Auditor",
    dialog_shortcuts_title: "Keyboard shortcuts",
    dialog_shortcuts_eyebrow: "Work faster",
    drop_overlay_title: "Release to upload",
    drop_overlay_desc: "Files are processed locally — nothing leaves this machine.",

    // Shortcuts
    shortcut_search: "Search documents",
    shortcut_upload: "Upload documents",
    shortcut_nav: "Next / previous document",
    shortcut_lists: "Review · Documents · Exceptions",
    shortcut_toggle_view: "Toggle OCR text / original",
    shortcut_assistant: "Ask the assistant",
    shortcut_theme: "Cycle theme",
    shortcut_save_field: "Save the focused field",
    shortcut_help: "Show this help",

    // Prompts
    prompt_why: "Why does this document need attention?",
    prompt_summarize: "Summarize this document",
    prompt_corrections: "Which fields were corrected?",
    prompt_registration: "What is the registration status?",
    prompt_audit: "Show the audit history",
  },

  it: {
    // Navigation & header
    nav_queue: "Coda di revisione",
    nav_documents: "Tutti i documenti",
    nav_exceptions: "Eccezioni",
    nav_shortcuts: "Scorciatoie da tastiera",
    nav_theme: "Cambia tema",
    nav_settings: "Impostazioni operatore",
    search_placeholder: "Cerca nel testo OCR, valori, riferimenti, nomi file",
    search_label: "Cerca documenti",
    stage_filter_all: "Tutti gli stati",
    stage_filter_label: "Stato del flusso",
    export: "Esporta",
    export_fields_csv: "Valori dei campi",
    export_jsonl: "Dataset di ricerca",
    export_jsonl_ocr: "Dataset + testo OCR",
    export_json: "Esportazioni convalidate",
    export_menu_label: "Dataset di ricerca",
    upload: "Carica",

    // Lists & Panes
    list_queue_title: "Coda di revisione",
    list_queue_eyebrow: "Revisione umana",
    list_documents_title: "Tutti i documenti",
    list_documents_eyebrow: "Archivio",
    list_exceptions_title: "Eccezioni",
    list_exceptions_eyebrow: "Richiede attenzione",
    list_empty: "Nessun documento trovato",

    // Workspace
    empty_title: "Trascina un documento per iniziare",
    empty_desc: "File di testo, PDF e immagini scansionate vengono elaborati localmente con OCR, classificati ed estratti. I valori incerti attendono la tua verifica.",
    empty_upload_btn: "Carica documenti",
    empty_browse_btn: "Esplora tutti",
    empty_scan_title: "Scansiona",
    empty_scan_desc: "Layer testuale, PDF o OCR Tesseract",
    empty_extract_title: "Estrai",
    empty_extract_desc: "Regole di tassonomia con segnali di confidenza",
    empty_verify_title: "Verifica",
    empty_verify_desc: "Revisione affiancata, tracciabilità completa",
    view_ocr_text: "Testo OCR",
    view_original: "Originale",
    fields_title: "Campi estratti",
    fields_empty: "Nessun campo estratto per questo documento.",
    fields_processing: "I campi appariranno al termine dell'estrazione.",
    not_found_in_text: "Non trovato nel testo",
    was_value: "era “{value}”",

    // Stages
    stage_acquired: "In coda per OCR",
    stage_ocr_executed: "Estrazione in corso",
    stage_to_be_verified: "Da verificare",
    stage_validated: "Validato",
    stage_protocol_pending: "Registrazione in corso",
    stage_protocol_registered: "Registrato a protocollo",
    stage_discarded: "Scartato",
    stage_failed: "Non riuscito",

    // Lifecycle
    lifecycle_intake: "Ricezione",
    lifecycle_ocr: "OCR",
    lifecycle_review: "Verifica",
    lifecycle_validated: "Validato",
    lifecycle_registering: "Registrazione",
    lifecycle_registered: "Registrato",

    // Reasons
    reason_low_confidence: "Bassa confidenza",
    reason_validation_pattern_mismatch: "Controllo formato fallito",
    reason_required_field_missing: "Campo obbligatorio mancante",
    reason_manual_policy_review: "Revisione manuale richiesta",

    // Actions
    action_complete_review: "Completa revisione",
    action_reopen_review: "Riapri revisione",
    action_retry_integration: "Riprova registrazione",
    action_request_reprocessing: "Rielabora",
    action_discard_document: "Scarta",
    action_cancel: "Annulla",
    action_save: "Salva",
    action_close: "Chiudi",
    action_confirm: "Conferma",
    action_resolve: "Risolvi",

    // Inspector
    tab_assistant: "Assistente",
    tab_issues: "Problemi",
    tab_registry: "Protocollo",
    tab_jobs: "Processi",
    tab_audit: "Audit",
    assistant_heading: "Assistente documentale",
    assistant_source_bounded: "Vincolato alle fonti",
    assistant_note: "Le risposte sono fondate esclusivamente sul testo, sui campi e sulla cronologia del documento. La decisione finale resta all'operatore.",
    assistant_prompt_placeholder: "Fai una domanda su questo documento…",
    assistant_ask_btn: "Invia",
    exceptions_heading: "Eccezioni",
    registration_heading: "Registrazione a protocollo",
    jobs_heading: "Processi in corso",
    audit_heading: "Traccia di controllo",
    audit_immutable: "Immutabile",

    // Dialogs
    dialog_upload_title: "Carica documenti",
    dialog_upload_eyebrow: "Ricezione",
    dialog_upload_dropzone: "Trascina qui i file o sfoglia",
    dialog_upload_type: "Tipo documento",
    dialog_upload_auto: "Rileva automaticamente",
    dialog_upload_institution: "Istituzione",
    dialog_upload_office: "Ufficio",
    dialog_upload_security: "Deduplicato con SHA-256 · elaborato localmente",
    dialog_reprocess_title: "Richiedi rielaborazione",
    dialog_reprocess_scope_legend: "Cosa vuoi rieseguire?",
    dialog_reprocess_scope_ext: "Estrazione metadati",
    dialog_reprocess_scope_ext_sub: "Mantiene il testo OCR corrente",
    dialog_reprocess_scope_ocr: "OCR ed estrazione",
    dialog_reprocess_scope_ocr_sub: "Rilegge il file originale dall'inizio",
    dialog_reprocess_comment: "Commento",
    dialog_reprocess_comment_ph: "Opzionale — registrato nella traccia di audit",
    dialog_reprocess_note: "Il lavoro di revisione in sospeso sarà annullato e ricreato dalla nuova esecuzione.",
    dialog_settings_title: "Impostazioni",
    dialog_settings_eyebrow: "Operatore",
    dialog_settings_name: "Il tuo nome",
    dialog_settings_name_meta: "registrato nella traccia di audit",
    dialog_settings_token: "Token API",
    dialog_settings_token_ph: "Necessario solo se il server imposta XTRACT_API_TOKEN",
    dialog_settings_token_meta: "Conservato solo nella sessione e inviato come intestazione Bearer.",
    dialog_settings_language: "Lingua",
    dialog_settings_pack: "Preset territoriale",
    dialog_settings_role: "Ruolo assegnato",
    role_admin: "Amministratore",
    role_supervisor: "Supervisore",
    role_operator: "Operatore",
    role_viewer: "Visualizzatore (Sola lettura)",
    role_auditor: "Revisore dei conti",
    dialog_shortcuts_title: "Scorciatoie da tastiera",
    dialog_shortcuts_eyebrow: "Lavora più velocemente",
    drop_overlay_title: "Rilascia per caricare",
    drop_overlay_desc: "I file vengono elaborati localmente — nessun dato lascia questa macchina.",

    // Shortcuts
    shortcut_search: "Cerca documenti",
    shortcut_upload: "Carica documenti",
    shortcut_nav: "Documento successivo / precedente",
    shortcut_lists: "Revisione · Documenti · Eccezioni",
    shortcut_toggle_view: "Alterna testo OCR / originale",
    shortcut_assistant: "Chiedi all'assistente",
    shortcut_theme: "Cambia tema",
    shortcut_save_field: "Salva il campo selezionato",
    shortcut_help: "Mostra questo aiuto",

    // Prompts
    prompt_why: "Perché questo documento richiede attenzione?",
    prompt_summarize: "Riassumi questo documento",
    prompt_corrections: "Quali campi sono stati modificati?",
    prompt_registration: "Qual è lo stato di registrazione?",
    prompt_audit: "Mostra la cronologia di audit",
  },

  es: {
    nav_queue: "Cola de revisión",
    nav_documents: "Todos los documentos",
    nav_exceptions: "Excepciones",
    nav_shortcuts: "Atajos de teclado",
    nav_theme: "Cambiar tema",
    nav_settings: "Configuración del operador",
    search_placeholder: "Buscar texto OCR, valores, referencias, nombres de archivo",
    search_label: "Buscar documentos",
    stage_filter_all: "Todos los estados",
    stage_filter_label: "Estado del flujo",
    export: "Exportar",
    export_fields_csv: "Valores de campos",
    export_jsonl: "Conjunto de investigación",
    export_jsonl_ocr: "Conjunto + texto OCR",
    export_json: "Exportaciones validadas",
    export_menu_label: "Conjuntos de investigación",
    upload: "Subir",

    list_queue_title: "Cola de revisión",
    list_queue_eyebrow: "Supervisión humana",
    list_documents_title: "Todos los documentos",
    list_documents_eyebrow: "Biblioteca",
    list_exceptions_title: "Excepciones",
    list_exceptions_eyebrow: "Requiere atención",
    list_empty: "No se encontraron documentos",

    empty_title: "Arrastra un documento para comenzar",
    empty_desc: "Los archivos se procesan localmente con OCR y extracción. Los valores inciertos esperan tu revisión.",
    empty_upload_btn: "Subir documentos",
    empty_browse_btn: "Explorar todo",
    empty_scan_title: "Escanear",
    empty_scan_desc: "Capa de texto, PDF o Tesseract OCR",
    empty_extract_title: "Extraer",
    empty_extract_desc: "Reglas taxonómicas con señales de confianza",
    empty_verify_title: "Verificar",
    empty_verify_desc: "Revisión conjunta, trazabilidad total",
    view_ocr_text: "Texto OCR",
    view_original: "Original",
    fields_title: "Campos extraídos",
    fields_empty: "No se extrajeron campos para este documento.",
    fields_processing: "Los campos aparecerán al completar la extracción.",
    not_found_in_text: "No encontrado en el texto",
    was_value: "era “{value}”",

    stage_acquired: "En cola para OCR",
    stage_ocr_executed: "Extrayendo",
    stage_to_be_verified: "Requiere revisión",
    stage_validated: "Validado",
    stage_protocol_pending: "Registrando",
    stage_protocol_registered: "Registrado",
    stage_discarded: "Descartado",
    stage_failed: "Fallido",

    lifecycle_intake: "Recepción",
    lifecycle_ocr: "OCR",
    lifecycle_review: "Revisión",
    lifecycle_validated: "Validado",
    lifecycle_registering: "Registrando",
    lifecycle_registered: "Registrado",

    reason_low_confidence: "Baja confianza",
    reason_validation_pattern_mismatch: "Fallo de formato",
    reason_required_field_missing: "Campo obligatorio faltante",
    reason_manual_policy_review: "Revisión manual requerida",

    action_complete_review: "Completar revisión",
    action_reopen_review: "Reabrir revisión",
    action_retry_integration: "Reintentar registro",
    action_request_reprocessing: "Reprocesar",
    action_discard_document: "Descartar",
    action_cancel: "Cancelar",
    action_save: "Guardar",
    action_close: "Cerrar",
    action_confirm: "Confirmar",
    action_resolve: "Resolver",

    tab_assistant: "Asistente",
    tab_issues: "Incidencias",
    tab_registry: "Registro",
    tab_jobs: "Procesos",
    tab_audit: "Auditoría",
    assistant_heading: "Asistente documental",
    assistant_source_bounded: "Basado en evidencias",
    assistant_note: "Respuestas basadas únicamente en el texto del documento. Las decisiones quedan en manos del operador.",
    assistant_prompt_placeholder: "Pregunta sobre este documento…",
    assistant_ask_btn: "Preguntar",
    exceptions_heading: "Excepciones",
    registration_heading: "Registro oficial",
    jobs_heading: "Trabajos de procesamiento",
    audit_heading: "Pista de auditoría",
    audit_immutable: "Inmutable",

    dialog_upload_title: "Subir documentos",
    dialog_upload_eyebrow: "Recepción",
    dialog_upload_dropzone: "Arrastra archivos aquí o examina",
    dialog_upload_type: "Tipo de documento",
    dialog_upload_auto: "Detectar automáticamente",
    dialog_upload_institution: "Institución",
    dialog_upload_office: "Oficina",
    dialog_upload_security: "Deduplicado con SHA-256 · procesado en el dispositivo",
    dialog_reprocess_title: "Solicitar reprocesamiento",
    dialog_reprocess_scope_legend: "¿Qué se debe volver a ejecutar?",
    dialog_reprocess_scope_ext: "Extracción de metadatos",
    dialog_reprocess_scope_ext_sub: "Mantiene el texto OCR actual",
    dialog_reprocess_scope_ocr: "OCR y extracción",
    dialog_reprocess_scope_ocr_sub: "Vuelve a leer el archivo original desde cero",
    dialog_reprocess_comment: "Comentario",
    dialog_reprocess_comment_ph: "Opcional — registrado en la pista de auditoría",
    dialog_reprocess_note: "El trabajo pendiente se cancelará y se recreará.",
    dialog_settings_title: "Configuración",
    dialog_settings_eyebrow: "Operador",
    dialog_settings_name: "Tu nombre",
    dialog_settings_name_meta: "registrado en la pista de auditoría",
    dialog_settings_token: "Token API",
    dialog_settings_token_ph: "Solo si el servidor requiere XTRACT_API_TOKEN",
    dialog_settings_token_meta: "Guardado solo en la sesión y enviado como encabezado Bearer.",
    dialog_settings_language: "Idioma",
    dialog_settings_pack: "Paquete de dominio",
    dialog_settings_role: "Rol asignado",
    role_admin: "Administrador",
    role_supervisor: "Supervisor",
    role_operator: "Operador",
    role_viewer: "Visualizador (Solo lectura)",
    role_auditor: "Auditor",
    dialog_shortcuts_title: "Atajos de teclado",
    dialog_shortcuts_eyebrow: "Trabaja más rápido",
    drop_overlay_title: "Suelta para subir",
    drop_overlay_desc: "Los archivos se procesan localmente.",

    shortcut_search: "Buscar documentos",
    shortcut_upload: "Subir documentos",
    shortcut_nav: "Documento siguiente / anterior",
    shortcut_lists: "Revisión · Documentos · Excepciones",
    shortcut_toggle_view: "Alternar texto OCR / original",
    shortcut_assistant: "Preguntar al asistente",
    shortcut_theme: "Cambiar tema",
    shortcut_save_field: "Guardar el campo enfocado",
    shortcut_help: "Mostrar esta ayuda",

    prompt_why: "¿Por qué necesita atención este documento?",
    prompt_summarize: "Resume este documento",
    prompt_corrections: "¿Qué campos fueron corregidos?",
    prompt_registration: "¿Cuál es el estado de registro?",
    prompt_audit: "Muestra el historial de auditoría",
  },

  fr: {
    nav_queue: "File de révision",
    nav_documents: "Tous les documents",
    nav_exceptions: "Exceptions",
    nav_shortcuts: "Raccourcis clavier",
    nav_theme: "Changer de thème",
    nav_settings: "Paramètres de l'opérateur",
    search_placeholder: "Rechercher dans le texte OCR, valeurs, références",
    search_label: "Rechercher des documents",
    stage_filter_all: "Tous les états",
    stage_filter_label: "État du flux",
    export: "Exporter",
    export_fields_csv: "Valeurs des champs",
    export_jsonl: "Jeu de données",
    export_jsonl_ocr: "Jeu de données + OCR",
    export_json: "Exports validés",
    export_menu_label: "Jeux de recherche",
    upload: "Importer",

    list_queue_title: "File de révision",
    list_queue_eyebrow: "Validation humaine",
    list_documents_title: "Tous les documents",
    list_documents_eyebrow: "Bibliothèque",
    list_exceptions_title: "Exceptions",
    list_exceptions_eyebrow: "Attention requise",
    list_empty: "Aucun document trouvé",

    empty_title: "Déposez un document pour commencer",
    empty_desc: "Traitement local par OCR et extraction. Les valeurs incertaines attendent votre vérification.",
    empty_upload_btn: "Importer des documents",
    empty_browse_btn: "Tout parcourir",
    empty_scan_title: "Numériser",
    empty_scan_desc: "Texte intégré, PDF ou Tesseract OCR",
    empty_extract_title: "Extraire",
    empty_extract_desc: "Règles taxonomiques avec indices de confiance",
    empty_verify_title: "Vérifier",
    empty_verify_desc: "Révision côte à côte, journal complet",
    view_ocr_text: "Texte OCR",
    view_original: "Original",
    fields_title: "Champs extraits",
    fields_empty: "Aucun champ extrait pour ce document.",
    fields_processing: "Les champs apparaîtront après extraction.",
    not_found_in_text: "Non trouvé dans le texte",
    was_value: "était «{value}»",

    stage_acquired: "En file pour OCR",
    stage_ocr_executed: "Extraction en cours",
    stage_to_be_verified: "À vérifier",
    stage_validated: "Validé",
    stage_protocol_pending: "Enregistrement en cours",
    stage_protocol_registered: "Enregistré",
    stage_discarded: "Rejeté",
    stage_failed: "Échec",

    lifecycle_intake: "Réception",
    lifecycle_ocr: "OCR",
    lifecycle_review: "Révision",
    lifecycle_validated: "Validé",
    lifecycle_registering: "Enregistrement",
    lifecycle_registered: "Enregistré",

    reason_low_confidence: "Faible confiance",
    reason_validation_pattern_mismatch: "Format non conforme",
    reason_required_field_missing: "Champ obligatoire manquant",
    reason_manual_policy_review: "Révision manuelle demandée",

    action_complete_review: "Valider la révision",
    action_reopen_review: "Rouvrir la révision",
    action_retry_integration: "Réessayer l'enregistrement",
    action_request_reprocessing: "Retraiter",
    action_discard_document: "Rejeter",
    action_cancel: "Annuler",
    action_save: "Enregistrer",
    action_close: "Fermer",
    action_confirm: "Confirmer",
    action_resolve: "Résoudre",

    tab_assistant: "Assistant",
    tab_issues: "Anomalies",
    tab_registry: "Registre",
    tab_jobs: "Traitements",
    tab_audit: "Audit",
    assistant_heading: "Assistant documentaire",
    assistant_source_bounded: "Ancré aux sources",
    assistant_note: "Réponses fondées strictement sur le texte du document.",
    assistant_prompt_placeholder: "Posez une question sur ce document…",
    assistant_ask_btn: "Envoyer",
    exceptions_heading: "Exceptions",
    registration_heading: "Enregistrement officiel",
    jobs_heading: "Traitements en cours",
    audit_heading: "Piste d'audit",
    audit_immutable: "Immuable",

    dialog_upload_title: "Importer des documents",
    dialog_upload_eyebrow: "Réception",
    dialog_upload_dropzone: "Déposez des fichiers ici ou parcourez",
    dialog_upload_type: "Type de document",
    dialog_upload_auto: "Détection automatique",
    dialog_upload_institution: "Institution",
    dialog_upload_office: "Service",
    dialog_upload_security: "Déduplication SHA-256 · traitement local",
    dialog_reprocess_title: "Demander un retraitement",
    dialog_reprocess_scope_legend: "Que souhaitez-vous réexécuter ?",
    dialog_reprocess_scope_ext: "Extraction des métadonnées",
    dialog_reprocess_scope_ext_sub: "Conserve le texte OCR actuel",
    dialog_reprocess_scope_ocr: "OCR et extraction",
    dialog_reprocess_scope_ocr_sub: "Relit le document depuis le début",
    dialog_reprocess_comment: "Commentaire",
    dialog_reprocess_comment_ph: "Optionnel — consigné dans la piste d'audit",
    dialog_reprocess_note: "Les tâches en attente seront annulées et recréées.",
    dialog_settings_title: "Paramètres",
    dialog_settings_eyebrow: "Opérateur",
    dialog_settings_name: "Votre nom",
    dialog_settings_name_meta: "enregistré dans la piste d'audit",
    dialog_settings_token: "Jeton API",
    dialog_settings_token_ph: "Requis seulement si XTRACT_API_TOKEN est configuré",
    dialog_settings_token_meta: "Conservé en session uniquement et transmis via en-tête Bearer.",
    dialog_settings_language: "Langue",
    dialog_settings_pack: "Pack de domaine",
    dialog_settings_role: "Rôle assigné",
    role_admin: "Administrateur",
    role_supervisor: "Superviseur",
    role_operator: "Opérateur",
    role_viewer: "Lecteur (Lecture seule)",
    role_auditor: "Auditeur",
    dialog_shortcuts_title: "Raccourcis clavier",
    dialog_shortcuts_eyebrow: "Gagner du temps",
    drop_overlay_title: "Relâchez pour importer",
    drop_overlay_desc: "Les fichiers sont traités localement.",

    shortcut_search: "Rechercher des documents",
    shortcut_upload: "Importer des documents",
    shortcut_nav: "Document suivant / précédent",
    shortcut_lists: "Révision · Documents · Exceptions",
    shortcut_toggle_view: "Basculer texte OCR / original",
    shortcut_assistant: "Interroger l'assistant",
    shortcut_theme: "Changer de thème",
    shortcut_save_field: "Enregistrer le champ sélectionné",
    shortcut_help: "Afficher cette aide",

    prompt_why: "Pourquoi ce document requiert-il une attention ?",
    prompt_summarize: "Résumer ce document",
    prompt_corrections: "Quels champs ont été corrigés ?",
    prompt_registration: "Quel est le statut d'enregistrement ?",
    prompt_audit: "Afficher l'historique d'audit",
  },

  de: {
    nav_queue: "Prüfungs-Warteschlange",
    nav_documents: "Alle Dokumente",
    nav_exceptions: "Ausnahmen",
    nav_shortcuts: "Tastaturkürzel",
    nav_theme: "Design wechseln",
    nav_settings: "Bediener-Einstellungen",
    search_placeholder: "OCR-Text, Werte, Referenzen, Dateinamen durchsuchen",
    search_label: "Dokumente durchsuchen",
    stage_filter_all: "Alle Status",
    stage_filter_label: "Workflow-Status",
    export: "Exportieren",
    export_fields_csv: "Feldwerte",
    export_jsonl: "Forschungsdatensatz",
    export_jsonl_ocr: "Datensatz + OCR-Text",
    export_json: "Validierte Exporte",
    export_menu_label: "Forschungsdatensätze",
    upload: "Hochladen",

    list_queue_title: "Prüfungs-Warteschlange",
    list_queue_eyebrow: "Menschliche Prüfung",
    list_documents_title: "Alle Dokumente",
    list_documents_eyebrow: "Archiv",
    list_exceptions_title: "Ausnahmen",
    list_exceptions_eyebrow: "Aufmerksamkeit erforderlich",
    list_empty: "Keine Dokumente gefunden",

    empty_title: "Dokument ablegen, um zu beginnen",
    empty_desc: "Dateien werden lokal per OCR verarbeitet und extrahiert. Unsichere Werte warten auf Ihre Prüfung.",
    empty_upload_btn: "Dokumente hochladen",
    empty_browse_btn: "Alle durchsuchen",
    empty_scan_title: "Scannen",
    empty_scan_desc: "Textebene, PDF oder Tesseract-OCR",
    empty_extract_title: "Extrahieren",
    empty_extract_desc: "Taxonomieregeln mit Konfidenzwerten",
    empty_verify_title: "Verifizieren",
    empty_verify_desc: "Direkter Vergleich, vollständiger Prüfpfad",
    view_ocr_text: "OCR-Text",
    view_original: "Original",
    fields_title: "Extrahierte Felder",
    fields_empty: "Für dieses Dokument wurden keine Felder extrahiert.",
    fields_processing: "Felder erscheinen nach der Extraktion.",
    not_found_in_text: "Nicht im Text gefunden",
    was_value: "war „{value}“",

    stage_acquired: "In Warteschlange für OCR",
    stage_ocr_executed: "Extraktion läuft",
    stage_to_be_verified: "Prüfung erforderlich",
    stage_validated: "Validiert",
    stage_protocol_pending: "Registrierung läuft",
    stage_protocol_registered: "Registriert",
    stage_discarded: "Verworfen",
    stage_failed: "Fehlgeschlagen",

    lifecycle_intake: "Eingang",
    lifecycle_ocr: "OCR",
    lifecycle_review: "Prüfung",
    lifecycle_validated: "Validiert",
    lifecycle_registering: "Registrierung",
    lifecycle_registered: "Registriert",

    reason_low_confidence: "Geringe Konfidenz",
    reason_validation_pattern_mismatch: "Formatprüfung fehlgeschlagen",
    reason_required_field_missing: "Pflichtfeld fehlt",
    reason_manual_policy_review: "Manuelle Überprüfung angefordert",

    action_complete_review: "Prüfung abschließen",
    action_reopen_review: "Prüfung wiedereröffnen",
    action_retry_integration: "Registrierung wiederholen",
    action_request_reprocessing: "Erneut verarbeiten",
    action_discard_document: "Verwerfen",
    action_cancel: "Abbrechen",
    action_save: "Speichern",
    action_close: "Schließen",
    action_confirm: "Bestätigen",
    action_resolve: "Beheben",

    tab_assistant: "Assistent",
    tab_issues: "Probleme",
    tab_registry: "Protokoll",
    tab_jobs: "Aufträge",
    tab_audit: "Audit",
    assistant_heading: "Dokumenten-Assistent",
    assistant_source_bounded: "Quellengebunden",
    assistant_note: "Antworten stützen sich ausschließlich auf dieses Dokument.",
    assistant_prompt_placeholder: "Frage zu diesem Dokument stellen…",
    assistant_ask_btn: "Senden",
    exceptions_heading: "Ausnahmen",
    registration_heading: "Protokoll-Registrierung",
    jobs_heading: "Verarbeitungsaufträge",
    audit_heading: "Prüfpfad",
    audit_immutable: "Unveränderlich",

    dialog_upload_title: "Dokumente hochladen",
    dialog_upload_eyebrow: "Eingang",
    dialog_upload_dropzone: "Dateien hier ablegen oder durchsuchen",
    dialog_upload_type: "Dokumenttyp",
    dialog_upload_auto: "Automatisch erkennen",
    dialog_upload_institution: "Institution",
    dialog_upload_office: "Abteilung",
    dialog_upload_security: "SHA-256 dedupliziert · auf dem Gerät verarbeitet",
    dialog_reprocess_title: "Erneute Verarbeitung anfordern",
    dialog_reprocess_scope_legend: "Was soll erneut ausgeführt werden?",
    dialog_reprocess_scope_ext: "Metadaten-Extraktion",
    dialog_reprocess_scope_ext_sub: "Behält den aktuellen OCR-Text bei",
    dialog_reprocess_scope_ocr: "OCR und Extraktion",
    dialog_reprocess_scope_ocr_sub: "Liest die Datei von Grund auf neu",
    dialog_reprocess_comment: "Kommentar",
    dialog_reprocess_comment_ph: "Optional — im Prüfpfad erfasst",
    dialog_reprocess_note: "Ausstehende Prüfungen werden abgebrochen und neu erstellt.",
    dialog_settings_title: "Einstellungen",
    dialog_settings_eyebrow: "Bediener",
    dialog_settings_name: "Ihr Name",
    dialog_settings_name_meta: "im Prüfpfad erfasst",
    dialog_settings_token: "API-Token",
    dialog_settings_token_ph: "Nur erforderlich, wenn XTRACT_API_TOKEN gesetzt ist",
    dialog_settings_token_meta: "Wird nur in der Sitzung gespeichert und als Bearer-Header gesendet.",
    dialog_settings_language: "Sprache",
    dialog_settings_pack: "Domänenpaket",
    dialog_settings_role: "Zugewiesene Rolle",
    role_admin: "Administrator",
    role_supervisor: "Supervisor",
    role_operator: "Operator",
    role_viewer: "Betrachter (Nur Lesezugriff)",
    role_auditor: "Auditor",
    dialog_shortcuts_title: "Tastaturkürzel",
    dialog_shortcuts_eyebrow: "Schneller arbeiten",
    drop_overlay_title: "Loslassen zum Hochladen",
    drop_overlay_desc: "Dateien werden lokal verarbeitet.",

    shortcut_search: "Dokumente durchsuchen",
    shortcut_upload: "Dokumente hochladen",
    shortcut_nav: "Nächstes / vorheriges Dokument",
    shortcut_lists: "Prüfung · Dokumente · Ausnahmen",
    shortcut_toggle_view: "OCR-Text / Original umschalten",
    shortcut_assistant: "Assistent fragen",
    shortcut_theme: "Design wechseln",
    shortcut_save_field: "Fokussiertes Feld speichern",
    shortcut_help: "Diese Hilfe anzeigen",

    prompt_why: "Warum benötigt dieses Dokument Aufmerksamkeit?",
    prompt_summarize: "Dieses Dokument zusammenfassen",
    prompt_corrections: "Welche Felder wurden korrigiert?",
    prompt_registration: "Wie ist der Registrierungsstatus?",
    prompt_audit: "Audit-Verlauf anzeigen",
  },
};

let activeLocale = "en";
const listeners = new Set();

export function currentLocale() {
  return activeLocale;
}

export function initLocale(preferredLocale) {
  let stored = null;
  try {
    stored = window.localStorage.getItem("xtract.locale");
  } catch {
    /* storage unavailable */
  }

  const browserLang = (navigator.language || "en").slice(0, 2).toLowerCase();
  const candidate = stored || preferredLocale || (DICTIONARIES[browserLang] ? browserLang : "en");
  setLocale(DICTIONARIES[candidate] ? candidate : "en", false);
}

export function setLocale(locale, persist = true) {
  if (!DICTIONARIES[locale]) locale = "en";
  activeLocale = locale;
  document.documentElement.lang = locale;
  if (persist) {
    try {
      window.localStorage.setItem("xtract.locale", locale);
    } catch {
      /* storage unavailable */
    }
  }
  listeners.forEach((fn) => {
    try {
      fn(locale);
    } catch (err) {
      console.error("i18n listener error", err);
    }
  });
}

export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function t(key, params = {}) {
  const dict = DICTIONARIES[activeLocale] || DICTIONARIES.en;
  let text = dict[key] !== undefined ? dict[key] : DICTIONARIES.en[key];
  if (text === undefined) text = key;
  if (typeof text !== "string") return text;
  for (const [k, v] of Object.entries(params)) {
    text = text.replaceAll(`{${k}}`, String(v));
  }
  return text;
}

export function getStageLabel(stage) {
  return t(`stage_${stage}`, stage);
}

export function getReasonLabel(code) {
  return t(`reason_${code}`, code);
}

export function getActionLabel(code) {
  return t(`action_${code}`, code);
}

export function getLifecycleSteps() {
  return [
    ["acquired", t("lifecycle_intake")],
    ["ocr_executed", t("lifecycle_ocr")],
    ["to_be_verified", t("lifecycle_review")],
    ["validated", t("lifecycle_validated")],
    ["protocol_pending", t("lifecycle_registering")],
    ["protocol_registered", t("lifecycle_registered")],
  ];
}

export function getListMeta(key) {
  return {
    title: t(`list_${key}_title`),
    eyebrow: t(`list_${key}_eyebrow`),
  };
}

export function getSuggestedPrompts() {
  return [
    t("prompt_why"),
    t("prompt_summarize"),
    t("prompt_corrections"),
    t("prompt_registration"),
    t("prompt_audit"),
  ];
}

export function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  root.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  });
  root.querySelectorAll("[data-i18n-tip]").forEach((el) => {
    el.dataset.tip = t(el.dataset.i18nTip);
  });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
}
