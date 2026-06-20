# AttendIA

**Resolvemos tus problemas en tiempo récord**

## El problema

Las pequeñas empresas y startups, a diferencia de las grandes corporaciones, normalmente no cuentan con un servicio como Zendesk para organizar las decenas de correos que reciben a diario. Según Isaac Dunet, comercializador de contenidos, una microempresa o startup recibe entre 30 y 100 correos diarios (150 a 500 por semana) por cuenta de correo principal, aunque solo entre el 10% y el 20% suelen ser críticos para el negocio. Esta cifra varía considerablemente según el canal y el rol dentro de la empresa encargado de resolver los problemas.

Adicionalmente, una investigación de McKinsey sobre productividad laboral señala que los empleados dedican aproximadamente el 28% de su semana laboral a gestionar correos electrónicos, de los cuales casi el 60% corresponde a información innecesaria o de poca relevancia. Esto se traduce, en promedio, en 10 a 11 horas semanales de trabajo improductivo por empresa.

## La solución

AttendIA es una plataforma desplegada en la nube cuya función principal es organizar y priorizar de forma automática la cantidad masiva de correos electrónicos que recibe una empresa, enviándolos a sus respectivas áreas de trabajo, todo esto con ayuda de Inteligencia Artificial.

Como propuesta diferencial, para cada correo que ya ha sido respondido, se utiliza IA para analizar la respuesta brindada en primera instancia y elaborar una respuesta sugerida para casos similares:

- Si el ticket tiene **alta urgencia**, la respuesta generada por IA no se envía automáticamente: queda pendiente de verificación por parte del usuario, quien formula la respuesta definitiva.
- Si el ticket tiene **baja urgencia**, la respuesta sugerida sí puede enviarse, previa validación del área encargada.

## Criterios para selección de prioridad

| Criterio | Descripción |
|---|---|
| Fecha de envío | En qué momento fue enviado el correo y cuánto tiempo ha pasado sin recibir respuesta |
| Emisor | Si el emisor es una persona jurídica o natural, para identificar posibles alianzas o inversiones |
| Palabras clave | Términos como pagos, fechas límite, entre otros |
| Historial de respuestas | Si la empresa ya había respondido previamente algún correo de ese emisor |

## Flujo principal de la aplicación

### Login empresa

La microempresa es quien envía un CSV con todos los correos que ha recibido y desea organizar. Al registrarse, cada microempresa asigna un nombre identificador y define el número de áreas de trabajo que tiene; ambos campos son obligatorios, ya que se usan para asignar cada email a un área específica encargada de resolver los tickets correspondientes.

Una vez registrada, la empresa puede crear usuarios y asignarlos a las distintas áreas. Estas credenciales son las que la empresa distribuye a sus empleados para que accedan a la plataforma con rol de empleado.

### Login empleado

Los empleados ingresan con las credenciales que les brinda su empresa. Al iniciar sesión, acceden a un espacio de trabajo donde se listan todos los correos pendientes por resolver, ordenados por prioridad. Desde la misma plataforma pueden leer el contenido de cada petición y responderla. Una vez respondida, el ticket cambia a estado **resuelto**, y se notifica al emisor original mediante correo electrónico.

### Creación de la petición

La empresa envía a la plataforma un archivo CSV con todos los correos que desea ordenar por prioridad. Ejemplo de entrada esperada (propuesta de payload para la Lambda):

```json
{
  "Tenant_Id": "Nombre del receptor del correo",
  "Contacto": "Nombre del emisor del correo",
  "Nombre": "Nombre de la cabecera del correo",
  "Descripcion": "Contenido del correo electrónico",
  "Area": "Área de trabajo a la que pertenece"
}
```

### Obtención de tickets

Los mensajes provenientes del CSV son procesados por la LLM, que les asigna un orden de prioridad como nuevo atributo dentro del JSON. Este JSON enriquecido se envía a la base de datos para que las áreas correspondientes puedan consultarlo:

```json
{
  "Tenant_Id": "Nombre del receptor del correo",
  "Contacto": "Nombre del emisor del correo",
  "Nombre": "Nombre de la cabecera del correo",
  "Descripcion": "Contenido del correo electrónico",
  "Area": "Área de trabajo a la que pertenece"
}
```

Si se requieren atributos adicionales, el LLM los incorpora directamente al JSON antes de enviarlo a la tabla DynamoDB. Los atributos mencionados arriba son obligatorios, ya que son los mínimos necesarios para que el área encargada pueda resolver el ticket.

### Resolución de tickets

Cada área de trabajo puede revisar todos los tickets que tiene asignados, ya clasificados por la LLM. Gracias al orden de prioridad asignado, los encargados resuelven los tickets de mayor a menor importancia desde la misma plataforma. Cuando el trabajador envía su respuesta, el ticket cambia de estado de **pendiente** a **resuelto**.

## Funciones Lambda

### Auth

**Crear_Usuario** — Registra usuarios en la tabla de DynamoDB, validando estrictamente sus datos según el rol asignado (`admin` o `empleado`). Extrae la información del body, verifica que no falten campos obligatorios (nombre de la empresa para administradores, área de trabajo para empleados) y encripta la contraseña con SHA-256. Comprueba que el correo no esté duplicado dentro de la misma organización y, de ser correcto, guarda al nuevo usuario respondiendo con HTTP 201 sin exponer datos sensibles.

**Login_Usuario** — Gestiona el inicio de sesión. Recibe `tenant_id`, correo y contraseña, y busca coincidencias exactas en la tabla de usuarios. Si las credenciales son válidas, genera (con la librería `uuid`) un token de acceso temporal con vigencia de 8 horas, registrándolo en una tabla secundaria junto a una marca de tiempo para que DynamoDB lo elimine automáticamente al expirar. Responde con HTTP 200.

**Validar_Token** — Funciona como autorizador de sesión. Extrae el token desde tres posibles orígenes (parámetros directos, cuerpo de la petición o cabecera `Authorization`) y lo busca en la tabla de sesiones. Si el token no existe o ya caducó, deniega el acceso con HTTP 403; si es válido, responde HTTP 200.

**Actualizar_Areas** — Actualiza la lista de áreas de trabajo de una empresa en la tabla `t_usuarios`. Primero valida el token mediante una invocación Lambda-to-Lambda al servicio de autenticación, luego verifica en DynamoDB que el solicitante exista y tenga estrictamente el rol `admin`. Tras superar ambos filtros y validar el formato de lista, ejecuta un `update_item` sobre el campo `areas`, respondiendo con HTTP 200.

### Tickets

**Crear_Ticket** — Registra los tickets en la tabla `t_tickets`, validando los atributos obligatorios descritos anteriormente. Tras validar el token de acceso, responde con HTTP 201 si el ticket se creó correctamente.

**ObtenerTicket** — Obtiene todos los tickets ya clasificados por orden de prioridad desde DynamoDB. Requiere validar el token de sesión para autorizar el acceso a los datos.

**ResolverTicket** — Recibe del usuario del área de trabajo un body con `tenant_id`, el comentario o respuesta, y el destinatario. Cambia el estado del ticket de pendiente a resuelto, y envía un correo al emisor original notificando que su solicitud fue resuelta, incluyendo el mensaje brindado por el área encargada.

## Arquitectura

_(Diagrama de arquitectura pendiente de incluir)_

## Despliegue

> ⚠️ Esta sección está incompleta en la documentación original — pendiente de definir el nombre de la variable de entorno y el comando de despliegue exacto.

1. Editar la variable de entorno: `<pendiente de especificar>`
2. Ejecutar el comando de despliegue: `<pendiente de especificar>`
