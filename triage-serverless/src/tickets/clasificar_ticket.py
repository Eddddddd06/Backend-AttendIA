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
            score_clasificado = 50  # default seguro si la IA falla o no hay API key

            if client_groq:
                try:
                    areas_formateadas = "\n".join(f"- {a}" for a in areas_disponibles)

                    system_prompt = (
                        "Eres un asistente experto en triaje de soporte corporativo para una plataforma multi-tenant.\n\n"
                        "Analiza el correo y devuelve dos datos:\n\n"
                        "1. \"area\": el área a la que debe asignarse el ticket. Elige EXCLUSIVAMENTE una de estas opciones, "
                        f"escrita EXACTAMENTE como aparece aquí:\n{areas_formateadas}\n\n"
                        "2. \"score\": un número entero del 1 al 100 que represente la urgencia, donde 100 es máxima urgencia. "
                        "Para asignarlo evalúa estas señales en el correo:\n"
                        "- Menciones de pagos, facturas, montos o transacciones pendientes\n"
                        "- Fechas límite, plazos, palabras como 'urgente', 'hoy', 'inmediato'\n"
                        "- Si el remitente parece una empresa (razón social con S.A.C., S.R.L., E.I.R.L., Corp, "
                        "dominio de correo corporativo) en lugar de una persona natural, ya que suele implicar "
                        "alianzas o inversiones de mayor impacto\n"
                        "- Referencias a un reclamo o correo previo sin respuesta (ej. 'como les comenté', "
                        "'segunda vez que escribo')\n"
                        "- Reportes de fallas críticas del sistema o pérdidas económicas en curso\n\n"
                        "Responde EXCLUSIVAMENTE en este formato JSON, sin texto adicional:\n"
                        '{"area": "nombre_de_area", "score": numero_entero}'
                    )

                    user_prompt = (
                        f"Remitente: {nombre_cliente}\n"
                        f"Contacto: {contacto_cliente}\n"
                        f"Contenido del correo:\n\"{descripcion}\""
                    )

                    chat_completion = client_groq.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1
                    )

                    ai_response = json.loads(chat_completion.choices[0].message.content)

                    area_propuesta = str(ai_response.get('area', '')).strip()
                    if area_propuesta in areas_disponibles:
                        area_clasificada = area_propuesta
                    else:
                        print(f"[WARN] Área inexistente '{area_propuesta}'. Usando default.")

                    try:
                        score_clasificado = max(1, min(100, int(ai_response.get('score', 50))))
                    except (ValueError, TypeError):
                        print("[WARN] Score inválido devuelto por la IA. Usando default 50.")

                except Exception as ai_err:
                    print(f"[ERROR IA] Fallo en Groq, aplicando fallback automático: {ai_err}")
            else:
                print("[WARN] GROQ_API_KEY no configurada. Usando área y score por defecto.")

            # Banda de prioridad legible, calculada en código (no por la IA) para consistencia
            if score_clasificado >= 70:
                prioridad = "alta"
            elif score_clasificado >= 40:
                prioridad = "media"
            else:
                prioridad = "baja"

            tenant_area = f"{tenant_id}#{area_clasificada}"

            # ─────────────────────────────────────────────────────────────
            # PASO 3: Guardar ticket siguiendo el FORMATO REQUERIDO
            # ─────────────────────────────────────────────────────────────
            tabla_tickets = dynamodb.Table(TABLE_TICKETS)

            item_ticket = {
                'tenant_id': tenant_id,
                'ticket_id': ticket_id,
                'tenant_area': tenant_area,
                'score': score_clasificado,
                'prioridad': prioridad,

                'Tenant_Id': tenant_id,
                'Contacto': contacto_cliente,
                'Nombre': nombre_cliente,
                'Descripción': descripcion,
                'Area': area_clasificada,

                'estado': 'pendiente',
                'clasificado_en': datetime.now(timezone.utc).isoformat()
            }

            tabla_tickets.put_item(Item=item_ticket)

            print(f"[OK] clasificar_ticket - Ticket {ticket_id} guardado con éxito en el nuevo formato")
            resultados.append({'ticket_id': ticket_id, 'status': 'pendiente'})

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
