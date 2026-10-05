# Clasificador Inteligente de Emails para Aseguradoras

## 1. Visión del producto

Construir un sistema que lea automáticamente los emails recibidos por una aseguradora, identifique qué tipo de información contienen, determine su nivel de sensibilidad y los clasifique para facilitar:

- búsqueda y organización;
- routing automático;
- priorización;
- compliance;
- detección de información sensible;
- automatización de workflows;
- análisis histórico;
- revisión humana de casos ambiguos.

El sistema utilizará **JEV como motor de clasificación semántica**.

---

# 2. Flujo general

```text
Email recibido
      ↓
Ingesta
      ↓
Extracción y normalización
      ↓
JEV
      ↓
Clasificación
      ↓
Reglas / thresholds
      ↓
Base de datos
      ↓
Dashboard / búsqueda / automatizaciones
```

El email original debe conservarse junto con las clasificaciones generadas.

---

# 3. Información procesada

Para cada email se puede utilizar como contexto:

- subject;
- body;
- sender;
- recipients;
- fecha;
- thread;
- nombres de archivos adjuntos;
- texto extraído de adjuntos;
- metadata relevante.

Ejemplo:

```json
{
  "subject": "Documentación siniestro 48392",
  "sender": "cliente@email.com",
  "body": "Adjunto denuncia policial y fotos del accidente...",
  "attachments": [
    "denuncia.pdf",
    "foto1.jpg"
  ]
}
```

---

# 4. Modelo de clasificación

La clasificación no debe representarse mediante un único label.

Cada email tendrá múltiples dimensiones.

```text
Email
 ├── Primary Business Category
 ├── Secondary Categories
 ├── Sensitivity
 ├── Required Action
 ├── Priority
 └── Confidence
```

Esto permite representar correctamente emails que contienen múltiples tipos de información.

---

# 5. Clasificación por sensibilidad

## PUBLIC

Información que puede compartirse externamente sin producir daño comercial, legal o de privacidad.

Ejemplos:

- campañas de marketing;
- productos públicos;
- eventos;
- comunicados de prensa;
- partnerships ya anunciados;
- información disponible públicamente.

---

## INTERNAL

Información destinada al funcionamiento interno de la empresa pero que no posee un nivel particularmente alto de sensibilidad.

Ejemplos:

- reuniones internas;
- coordinación entre equipos;
- procedimientos;
- reportes operativos;
- planificación cotidiana;
- comunicaciones administrativas.

---

## CONFIDENTIAL

Información empresarial no pública cuya divulgación podría perjudicar comercialmente a la organización.

Ejemplos:

- estrategia comercial;
- pricing futuro;
- negociaciones;
- contratos todavía no anunciados;
- clientes todavía no anunciados;
- partnerships en negociación;
- resultados financieros internos;
- información privada de proveedores.

---

## HIGHLY_CONFIDENTIAL

Información cuya divulgación podría generar consecuencias legales, financieras, reputacionales o laborales significativas.

Ejemplos:

- despidos;
- reestructuraciones;
- fusiones y adquisiciones;
- investigaciones internas;
- incidentes de seguridad;
- fraude;
- litigios importantes;
- secretos comerciales.

---

## PERSONAL_DATA

Información que identifica o permite identificar a una persona.

Ejemplos:

- DNI;
- CUIT/CUIL;
- dirección;
- teléfono;
- email personal;
- número de póliza asociado a una persona;
- cuenta bancaria;
- patente;
- datos financieros.

---

## SENSITIVE_PERSONAL_DATA

Información personal especialmente delicada o protegida.

Ejemplos:

- información médica;
- diagnósticos;
- discapacidad;
- biometría;
- historial clínico;
- información médica asociada a un siniestro.

Un email puede tener simultáneamente varios labels de sensibilidad.

---

# 6. Clasificación de negocio

## NEW_LEAD

Persona o empresa que manifiesta interés en convertirse en cliente y todavía no posee una póliza asociada a esa solicitud.

---

## QUOTE_REQUEST

Solicitud de precio, condiciones o alternativas de cobertura antes de contratar un seguro.

---

## NEW_POLICY

Comunicación relacionada con la creación, emisión o confirmación de una nueva póliza.

---

## POLICY_RENEWAL

Comunicación relacionada con la renovación o continuidad de una póliza existente.

---

## POLICY_CHANGE

Cambio solicitado sobre una póliza existente.

Puede incluir:

- cobertura;
- beneficiarios;
- vehículo;
- domicilio;
- suma asegurada;
- condiciones particulares.

---

## POLICY_CANCELLATION

Solicitud, aviso o procesamiento de la baja o cancelación de una póliza.

---

## CLAIM_NEW

Primera comunicación informando un evento potencialmente cubierto por un seguro.

Ejemplos:

- choque;
- robo;
- incendio;
- accidente;
- daño;
- pérdida.

---

## CLAIM_UPDATE

Nueva información relacionada con un siniestro previamente registrado.

---

## CLAIM_DOCUMENTATION

Documentación o evidencia relacionada con un siniestro.

Ejemplos:

- fotografías;
- presupuestos;
- denuncia policial;
- certificados;
- facturas;
- comprobantes.

---

## CLAIM_PAYMENT

Información relacionada con liquidación, indemnización o pago correspondiente a un siniestro.

---

## CLAIM_REJECTION

Comunicación relacionada con rechazo total o parcial de una cobertura o disputa sobre dicho rechazo.

---

## FRAUD_SUSPICION

Información relacionada con potencial fraude, falsificación o comportamiento irregular.

Puede tratarse tanto de una sospecha inicial como de una investigación.

---

## UNDERWRITING

Información utilizada para evaluar:

- si un riesgo debería asegurarse;
- bajo qué condiciones;
- con qué límites;
- a qué precio.

---

## BROKER_AGENT

Comunicaciones con productores, brokers, agentes u otros intermediarios.

---

## REINSURANCE

Información relacionada con reaseguros.

Incluye:

- cesión de riesgo;
- tratados;
- facultativos;
- comunicación con reaseguradoras.

---

## COMPLAINT

Reclamo, insatisfacción o disputa presentada por un cliente o tercero.

---

## LEGAL

Información relacionada con cuestiones jurídicas.

Ejemplos:

- demandas;
- cartas documento;
- intimaciones;
- abogados;
- procesos judiciales;
- consultas legales.

---

## REGULATORY

Información relacionada con:

- reguladores;
- auditorías;
- compliance;
- requerimientos oficiales;
- investigaciones regulatorias.

---

## PARTNERSHIP

Negociación o gestión de acuerdos comerciales o estratégicos con otras empresas.

---

## SUPPLIER

Comunicación con proveedores externos.

Por ejemplo:

- talleres;
- grúas;
- clínicas;
- peritos;
- inspectores;
- servicios tercerizados.

---

## PAYMENT_BILLING

Información relacionada con pagos y facturación.

Ejemplos:

- primas;
- cuotas;
- mora;
- facturas;
- devoluciones;
- cobros.

---

# 7. Clasificación de acción

Además del contenido, el sistema debe determinar qué debería ocurrir con el email.

Labels iniciales:

```text
NO_ACTION
REPLY_REQUIRED
DOCUMENT_REQUIRED
APPROVAL_REQUIRED
ESCALATE
URGENT
```

Estos labels pueden coexistir.

Ejemplo:

```text
REPLY_REQUIRED
ESCALATE
URGENT
```

---

# 8. Prioridad

La prioridad puede ser:

```text
LOW
NORMAL
HIGH
CRITICAL
```

Alternativamente, JEV puede devolver una escala numérica:

```text
1 - 5
```

que luego se convierte mediante reglas internas.

---

# 9. Cómo se utiliza JEV

JEV no debe recibir simplemente una lista enorme de categorías y preguntarle:

> “¿Cuál es esta?”

La decisión debe dividirse en preguntas pequeñas y claras.

Ejemplo:

```text
Does this email report a new insurance claim?

YES
NO
```

```text
Does this email contain documentation supporting an insurance claim?

YES
NO
```

```text
Does this email contain personally identifiable information?

YES
NO
```

```text
Does this email contain sensitive medical information?

YES
NO
```

```text
Does this email discuss suspected fraud?

YES
NO
```

JEV devuelve una probabilidad asociada a cada decisión.

Ejemplo:

```json
{
  "new_claim": 0.96,
  "claim_documentation": 0.81,
  "personal_data": 0.97,
  "fraud_suspicion": 0.08
}
```

Las políticas del producto convierten esas probabilidades en labels.

---

# 10. Primary y Secondary Categories

Un email puede estar relacionado con varias categorías.

Por lo tanto se almacenará:

```text
primary_category
secondary_categories[]
```

Ejemplo:

```json
{
  "primary_category": "CLAIM_NEW",
  "secondary_categories": [
    "CLAIM_DOCUMENTATION"
  ]
}
```

La categoría primaria representa la intención principal del email.

Las secundarias representan información adicional detectada.

---

# 11. Confidence y revisión humana

No todos los resultados deben automatizarse.

Ejemplo inicial de thresholds:

```text
confidence >= 0.90
→ clasificación automática

confidence >= 0.65 && < 0.90
→ clasificación + UNCERTAIN

confidence < 0.65
→ HUMAN_REVIEW
```

Estos valores deberán ajustarse utilizando emails reales.

Para categorías particularmente sensibles pueden establecerse thresholds mayores.

Ejemplo:

```text
FRAUD_SUSPICION
HIGHLY_CONFIDENTIAL
LEGAL

Auto classification threshold: 0.95
```

---

# 12. Almacenamiento

Cada email debe almacenarse junto con su clasificación.

Modelo conceptual:

```text
emails
classification_results
classification_labels
human_reviews
```

## Email

```json
{
  "id": "email_123",
  "message_id": "...",
  "thread_id": "...",

  "sender": "cliente@email.com",
  "recipients": ["claims@insurance.com"],

  "subject": "Accidente vehículo",
  "body": "...",

  "received_at": "2026-10-05T14:32:00Z",

  "attachments": []
}
```

---

# 13. Resultado de clasificación

Ejemplo:

```json
{
  "email_id": "email_123",

  "primary_category": "CLAIM_NEW",

  "secondary_categories": [
    "CLAIM_DOCUMENTATION"
  ],

  "sensitivity": [
    "PERSONAL_DATA"
  ],

  "actions": [
    "REPLY_REQUIRED"
  ],

  "priority": "HIGH",

  "confidence": 0.96,

  "requires_human_review": false,

  "classifier_version": "insurance-email-v1",

  "classified_at": "2026-10-05T14:32:02Z"
}
```

---

# 14. Guardar probabilidades individuales

No deberíamos guardar solamente el resultado final.

También deberíamos conservar los scores originales de JEV.

Ejemplo:

```json
{
  "scores": {
    "claim_new": 0.96,
    "claim_documentation": 0.81,
    "personal_data": 0.97,
    "sensitive_personal_data": 0.12,
    "fraud_suspicion": 0.08,
    "legal": 0.04
  }
}
```

Esto permite posteriormente:

- cambiar thresholds sin reclasificar todos los emails;
- auditar decisiones;
- detectar errores;
- comparar versiones;
- evaluar mejoras del clasificador.

---

# 15. Versionado

Cada clasificación debe guardar qué versión del sistema la produjo.

Ejemplo:

```text
insurance-email-v1
insurance-email-v2
insurance-email-v3
```

Si cambian:

- definiciones;
- preguntas;
- thresholds;
- modelo;
- reglas;

podemos comparar resultados entre versiones.

---

# 16. Human Review

Los casos ambiguos deben entrar en una cola de revisión.

El reviewer podrá:

```text
Confirmar clasificación
Cambiar primary category
Agregar/quitar secondary labels
Cambiar sensibilidad
Modificar prioridad
```

La corrección debe almacenarse.

Ejemplo:

```json
{
  "review_status": "CORRECTED",
  "original_label": "CLAIM_UPDATE",
  "corrected_label": "CLAIM_NEW",
  "reviewed_at": "...",
  "reviewer_id": "..."
}
```

Estas correcciones pueden formar posteriormente un dataset de evaluación.

---

# 17. MVP

El MVP debería concentrarse en demostrar que la clasificación funciona correctamente.

### Input

Emails históricos o una integración con una casilla.

### Pipeline

```text
Email
↓
JEV
↓
Rules
↓
Database
↓
Simple dashboard
```

### Primera taxonomía

#### Sensibilidad

```text
PUBLIC
INTERNAL
CONFIDENTIAL
HIGHLY_CONFIDENTIAL
PERSONAL_DATA
SENSITIVE_PERSONAL_DATA
```

#### Categorías principales

```text
NEW_LEAD
QUOTE_REQUEST
NEW_POLICY
POLICY_RENEWAL
POLICY_CHANGE
POLICY_CANCELLATION
CLAIM_NEW
CLAIM_UPDATE
CLAIM_DOCUMENTATION
PAYMENT_BILLING
COMPLAINT
FRAUD_SUSPICION
LEGAL
REGULATORY
PARTNERSHIP
OTHER
```

Las categorías más especializadas pueden añadirse posteriormente.

---

# 18. Métricas del MVP

Las métricas principales deberían ser:

### Classification accuracy

Porcentaje de emails correctamente clasificados.

### Precision / Recall por categoría

Especialmente importante para:

```text
FRAUD_SUSPICION
LEGAL
PERSONAL_DATA
SENSITIVE_PERSONAL_DATA
HIGHLY_CONFIDENTIAL
```

### Human Review Rate

```text
emails enviados a revisión
/
emails procesados
```

### False Negative Rate

Especialmente crítico para información sensible.

### Processing latency

Tiempo desde que entra un email hasta que está clasificado.

---

# 19. Evolución del producto

Después del clasificador pueden construirse funcionalidades adicionales.

### Smart routing

Enviar automáticamente:

```text
CLAIM_NEW → Claims
LEGAL → Legal
NEW_LEAD → Sales
FRAUD_SUSPICION → Fraud Team
```

### Search

Ejemplo:

> “Mostrar todos los siniestros de vehículos con documentación incompleta recibidos esta semana.”

### Alertas

Ejemplo:

> HIGHLY_CONFIDENTIAL enviado a destinatario externo.

### Analytics

Detectar:

- volumen de siniestros;
- tipos de reclamos;
- volumen de leads;
- tiempos de respuesta;
- tendencias de fraude;
- problemas recurrentes.

### Workflow automation

Por ejemplo:

```text
CLAIM_NEW
+
CLAIM_DOCUMENTATION
+
confidence > 0.95

↓

Crear caso automáticamente
```

---

# 20. Principio central del sistema

JEV genera **señales probabilísticas sobre el contenido del email**.

Las reglas de negocio de la aseguradora deciden qué hacer con esas señales.

La arquitectura queda separada en:

```text
JEV
↓
Understanding

Rules Engine
↓
Decision

Database / Workflows
↓
Action
```

Esto permite cambiar las políticas de la aseguradora sin tener que reemplazar el sistema de clasificación completo.
