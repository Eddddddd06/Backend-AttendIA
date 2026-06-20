import boto3
import json
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')


def lambda_handler(event, context):
    """
    Trigger: SQS - TicketsQueue (batchSize: 1)
    PRIVADO (sin HTTP): Procesamiento interno automático.

    Lee el mensaje de la cola, obtiene las áreas dinámicas de la empresa,
    simula la clasificación del ticket mediante un LLM (placeholder),
    y guarda el resultado en t_tickets.
    """
    resultados = []

    for record in event.get('Records', []):
        try:
            # ── Parsear mensaje de SQS ────────────────────────────────────
            message_body = json.loads(record['body'])

            tenant_id = message_body.get('tenant_id')
            ticket_id = message_body.get('ticket_id')
            descripcion = message_body.get('descripcion', '')
            nombre_cliente = message_body.get('nombre_cliente', 'Anónimo')
            contacto_cliente = message_body.get('contacto_cliente', '')
            creado_en = message_body.get('creado_en', datetime.now(timezone.utc).isoformat())

            if not tenant_id or not ticket_id:
                print(f"[ERROR] clasificar_ticket - mensaje malformado: {message_body}")
                continue

            # ─────────────────────────────────────────────────────────────
            # PASO 1: Obtener las áreas disponibles para esta empresa
            # ─────────────────────────────────────────────────────────────
            tabla_usuarios = dynamodb.Table(TABLE_USUARIOS)

            # Buscamos al admin de este tenant.
            # El GSI RolIndex tiene PK=rol, SK=tenant_id, así que podemos
            # filtrar directamente por ambos con KeyConditionExpression.
            admin_result = tabla_usuarios.query(
                IndexName='RolIndex',
                KeyConditionExpression='rol = :rol AND tenant_id = :tid',
                ExpressionAttributeValues={
                    ':rol': 'admin',
                    ':tid': tenant_id
                }
            )

            # Usar áreas definidas por el admin, o un listado por defecto
            areas_disponibles = []
            if admin_result.get('Items'):
                areas_disponibles = admin_result['Items'][0].get('areas', [])

            if not areas_disponibles:
                areas_disponibles = ["General", "Atención al Cliente"]

            # ─────────────────────────────────────────────────────────────
            # PASO 2: TODO - Lógica LLM
            #
            # Construir el prompt para el LLM con las áreas dinámicas:
            prompt = f"Clasifica la siguiente queja en UNA de estas categorías exactas: {areas_disponibles}. Queja: {descripcion}"
            print(f"[LLM PROMPT] {prompt}")
            #
            # Aquí llamarías a Groq/Bedrock/OpenAI pasándole el prompt:
            #   import groq
            #   client = groq.Client(api_key=os.environ['GROQ_API_KEY'])
            #   chat = client.chat.completions.create(
            #       model="llama3-8b-8192",
            #       messages=[{"role": "user", "content": prompt}]
            #   )
            #   resultado = json.loads(chat.choices[0].message.content)
            #   area  = resultado['area']
            #   score = resultado['score']
            # ─────────────────────────────────────────────────────────────

            # Valores simulados (Para desarrollo elegimos la primera área)
            area = areas_disponibles[0] if areas_disponibles else "General"
            score = 85

            # Clave compuesta para el GSI AreaScoreIndex
            # Formato: "tenant_id#area" → permite filtrar por empresa + área
            tenant_area = f"{tenant_id}#{area}"

            # ── Guardar ticket clasificado en DynamoDB ───────────────────
            tabla_tickets = dynamodb.Table(TABLE_TICKETS)
            tabla_tickets.put_item(
                Item={
                    'tenant_id': tenant_id,
                    'ticket_id': ticket_id,
                    'descripcion': descripcion,
                    'nombre_cliente': nombre_cliente,
                    'contacto_cliente': contacto_cliente,
                    'area': area,
                    'score': score,
                    'tenant_area': tenant_area,
                    'estado': 'clasificado',
                    'creado_en': creado_en,
                    'clasificado_en': datetime.now(timezone.utc).isoformat()
                }
            )

            print(f"[OK] clasificar_ticket - Ticket {ticket_id} → area={area}, score={score}")
            resultados.append({'ticket_id': ticket_id, 'status': 'clasificado'})

        except json.JSONDecodeError as e:
            print(f"[ERROR] clasificar_ticket - JSON inválido en SQS record: {e}")
            raise e  # SQS reintentará el mensaje
        except Exception as e:
            print(f"[ERROR] clasificar_ticket - ticket_id={message_body.get('ticket_id', 'N/A')}: {e}")
            raise e  # Re-lanzar para que SQS active el Dead Letter si está configurado

    return {
        'statusCode': 200,
        'body': json.dumps({
            'procesados': len(resultados),
            'resultados': resultados
        })
    }
