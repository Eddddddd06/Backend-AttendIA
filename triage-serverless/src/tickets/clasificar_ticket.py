import boto3
import json
import os
from datetime import datetime, timezone
import groq  # Asegúrate de incluirlo en tu layer o requirements.txt

dynamodb = boto3.resource('dynamodb')
TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')

# Inicializar cliente de Groq de forma global para reutilizar la conexión
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
client_groq = groq.Client(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def lambda_handler(event, context):
    """
    Trigger: SQS - TicketsQueue (batchSize: 1)
    Procesamiento automático de tickets individuales usando IA (Groq).
    Guarda en DynamoDB siguiendo estrictamente el formato multi-tenant requerido.
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

            if not tenant_id or not ticket_id:
                print(f"[ERROR] clasificar_ticket - Mensaje malformado: {message_body}")
                continue

            # ─────────────────────────────────────────────────────────────
            # PASO 1: Obtener las áreas disponibles para esta empresa
            # ─────────────────────────────────────────────────────────────
            tabla_usuarios = dynamodb.Table(TABLE_USUARIOS)

            admin_result = tabla_usuarios.query(
                IndexName='RolIndex',
                KeyConditionExpression='rol = :rol AND tenant_id = :tid',
                ExpressionAttributeValues={
                    ':rol': 'admin',
                    ':tid': tenant_id
                }
            )

            areas_disponibles = []
            if admin_result.get('Items'):
                areas_disponibles = admin_result['Items'][0].get('areas', [])

            # Fallback seguro si la empresa no configuró áreas
            if not areas_disponibles:
                areas_disponibles = ["Soporte Técnico", "Atención al Cliente", "Facturación"]

            # ─────────────────────────────────────────────────────────────
            # PASO 2: Integración con Inteligencia Artificial (Groq)
            # ─────────────────────────────────────────────────────────────
            area_clasificada = areas_disponibles[0]

            if client_groq:
                try:
                    system_prompt = (
                        "Eres un asistente experto en triaje de soporte corporativo. "
                        f"Tu tarea es analizar el correo de un usuario y clasificarlo ÚNICAMENTE en una de las siguientes áreas: {areas_disponibles}. "
                        "DEBES responder EXCLUSIVAMENTE en formato JSON con la siguiente estructura exacta: "
                        '{"area": "nombre_de_area"}'
                    )

                    user_prompt = f"Contenido del correo:\n\"{descripcion}\""

                    chat_completion = client_groq.chat.completions.create(
                        model="llama3-8b-8192",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1
                    )

                    ai_response = json.loads(chat_completion.choices[0].message.content)
                    area_propuesta = ai_response.get('area', '').strip()

                    # Control Anti-Alucinaciones
                    if area_propuesta in areas_disponibles:
                        area_clasificada = area_propuesta
                    else:
                        print(f"[WARN] La IA sugirió un área inexistente '{area_propuesta}'. Usando área por defecto.")

                except Exception as ai_err:
                    print(f"[ERROR IA] Fallo en Groq, aplicando fallback automático: {ai_err}")
            else:
                print("[WARN] GROQ_API_KEY no configurada. Usando área por defecto.")

            # ─────────────────────────────────────────────────────────────
            # PASO 3: Guardar ticket siguiendo el FORMATO REQUERIDO
            # ─────────────────────────────────────────────────────────────
            tabla_tickets = dynamodb.Table(TABLE_TICKETS)
            
            # Mapeo exacto solicitado por el usuario
            item_ticket = {
                'tenant_id': tenant_id,          # Mantenemos las claves primarias base si tu tabla las requiere para el particionamiento
                'ticket_id': ticket_id,          # (Hash y Range keys de DynamoDB de tu infraestructura)
                
                # Campos con el formato exacto solicitado:
                'Tenant_Id': tenant_id,          # Nombre del receptor del correo (Empresa/Tenant)
                'Contacto': contacto_cliente,    # Nombre/Email del emisor del correo
                'Nombre': nombre_cliente,        # Nombre de la cabecera del correo
                'Descripción': descripcion,      # Contenido del correo electrónico
                'Area': area_clasificada,        # A qué área de trabajo pertenece
                
                # Metadatos útiles de control interno (opcionales, puedes quitarlos si no los deseas)
                'estado': 'clasificado',
                'clasificado_en': datetime.now(timezone.utc).isoformat()
            }

            tabla_tickets.put_item(Item=item_ticket)

            print(f"[OK] clasificar_ticket - Ticket {ticket_id} guardado con éxito en el nuevo formato → Área: {area_clasificada}")
            resultados.append({'ticket_id': ticket_id, 'status': 'clasificado'})

        except Exception as e:
            print(f"[ERROR] clasificar_ticket - Error crítico procesando record SQS: {e}")
            raise e  # Lanzamos el error para que SQS maneje reintentos / DLQ

    return {
        'statusCode': 200,
        'body': json.dumps({
            'procesados': len(resultados),
            'resultados': resultados
        })
    }