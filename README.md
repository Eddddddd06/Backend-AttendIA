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

**Actualizar_Usuario** — Actualiza los valores de un Usuario que ha sido registrado por la empresa, previa validación del token de acceso. Si la petición de actualizar Usuario lo hace alguien que no es `admin` responde con HTTP 403. Caso contrario verifica que los campos hayan sido llenados correctamente y los modifica de forma dinámica dentro de la tabla Dynamo. Cuando todo los campos se completan responde con HTTP 200

**Logout_Usuario** — Extrae el token de sesión desde tres posibles orígenes, priorizando en ese orden. Una vez obtenido, ejecuta un `delete_item` sobre la tabla de tokens para invalidar la sesión de inmediato, el Lambda responde con HTTP 200 incluso si el token ya no existía por ejemplo, si ya había expirado.

**Mostrar Empleados** — Tras validar el token solicitante tiene estrictamente el rol `admin`, consulta en DynamoDB todos los usuarios con rol empleado pertenecientes al tenant_id del `admin`, usando el índice RolIndex. Por cada empleado devuelve su correo, área asignada, rol y nombre de empresa, y además recupera las áreas configuradas por el propio admin para incluirlas en la respuesta. Responde con HTTP 200 junto con el total de empleados encontrados y el listado completo.

### Tickets

**Crear_Ticket** — Registra los tickets en la tabla `t_tickets`, validando los atributos obligatorios descritos anteriormente. Tras validar el token de acceso, responde con HTTP 201 si el ticket se creó correctamente.

**ObtenerTicket** — Obtiene todos los tickets ya clasificados por orden de prioridad desde DynamoDB. Requiere validar el token de sesión para autorizar el acceso a los datos.

**ResolverTicket** — Recibe del usuario del área de trabajo un body con `tenant_id`, el comentario o respuesta, y el destinatario. Cambia el estado del ticket de pendiente a resuelto, y envía un correo al emisor original notificando que su solicitud fue resuelta, incluyendo el mensaje brindado por el área encargada.

**Cargar_csv**: Este Lambda permite a un administrador cargar un lote de tickets para su procesamiento. Inicia validando el token internamente para asegurar que el usuario tenga el rol de "admin" y heredar su tenant_id. Tras comprobar que el archivo no exceda el límite de seguridad (100 tickets) y verificar la longitud de cada descripción, genera un identificador único (UUID) por registro y lo encola de forma asíncrona en Amazon SQS. Finaliza retornando un HTTP 200 con un resumen exacto de los tickets encolados y los errores detectados.

**Clasificar_ticket**: Este Lambda es consumido automáticamente por la cola SQS para procesar tickets de forma individual. Primero, consulta en DynamoDB el catálogo de áreas disponibles para esa empresa específica. Luego, envía el contenido del ticket a la inteligencia artificial (Groq/Llama-3) mediante un prompt estricto, logrando que la IA devuelva el área asignada y un score de urgencia (1-100) en formato JSON. Finalmente, traduce el score a una prioridad legible y guarda el ticket clasificado en DynamoDB bajo una estructura multi-tenant.

**Enviar_email**: Este Lambda se encarga de despachar correos electrónicos a los clientes utilizando la API de Resend. Cuenta con soporte nativo para Amazon SNS; si detecta que el evento llega encapsulado en una notificación, lo desempaqueta de inmediato para extraer el JSON real. Una vez identificados el destinatario, el asunto y el cuerpo del mensaje, ejecuta la petición a través del SDK oficial de Resend y retorna un HTTP 200 con el ID de confirmación del envío.


## Arquitectura

<img width="1183" height="636" alt="image" src="https://github.com/user-attachments/assets/e1496534-03dd-4b73-b519-504a19e67cc0" />

## Despliegue

1. Fase de despliegue del backend.
   Este proyecto cuenta con un archivo requirements.txt el cual se tiene que ejecutar pues están presentes los módulos necesarios para el correcto funcionamiento del backend sobre todo para utilizar el modelo de LLM. Además se tienen que incluir estas variables que son las credenciales de las APIs que se están utilizando.
   
   ```bash
     pip3 install -r requirements.txt -t .
   ```
   
   Para desplegar el backend cabe aclarar que este tiene dos archivos importantes, los cuales son serverless.yml y requeriments.txt. En primer lugar, cabe
   aclarar que para poder hacer despliegues en awsacademy, nosotros utilizamos LabRole para administrar, crear y configurar una amplia variedad de servicios en la consola de AWS. En nuestro caso para crear las tablas DynamoDB, pilas en CloudFormation, lambdas y ApiGateway.
   El apartado `role: arn:aws:iam::${aws:accountId}:role/LabRole` la variable accountId recibe el Id de la cuenta Aws que está ejecutando en ese momento para utilizar el rol "LabRole". Luego de manera interna asigna en environment los nombres que van a utilizar las distintas tablas DynamoDB. Seguidamente cada parte del serverless.yml inicializa los lambdas con los cuales va a trabajar el backend y asigna sus respectivos caminos. Cada uno tiene un request, donde se le asigna una plantilla `application/json` que será la forma en que Amazon API Gateway, en lugar de enviar una petición HTTP cruda directamente a AWS Lambda, le indique que información específica necesita y la arme en un formato JSON limpio y estructurado.
   Para correr este comando se necesita tener serverless instalado, los comandos necesarios son:

   ```bash
     sudo npm install -g serverless
     serverless login
     sls deploy
   ```
    
3. Fase de despliegue del frontend.

   Al estar desplegado en Amplify solo es crear una applicación dentro del servicio de AWS Amplify y alojar lo que hay en el repositorio de Frontend de AttendIA.
   
