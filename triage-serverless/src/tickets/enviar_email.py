import resend
import json
import os

# Inicializa el cliente usando la API Key segura de las variables de entorno
resend.api_key = os.environ.get('RESEND_API_KEY')

def lambda_handler(event, context):
    try:
        print(f"[INFO] Evento recibido para enviar correo vía Resend: {json.dumps(event)}")
        
        to_email = event.get('to_email')
        subject = event.get('subject', 'Actualización de tu Ticket')
        body_content = event.get('body_content', 'Tu ticket ha sido actualizado.')

        if not to_email:
            print("[ERROR] No se proporcionó el correo de destino ('to_email')")
            return {'statusCode': 400, 'body': 'Falta el correo de destino.'}

        # Resend en su plan gratuito te permite enviar correos desde 'onboarding@resend.dev'
        # hacia tu propio correo con el que te registraste.
        params = {
            "from": "AttendIA <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "text": body_content,
        }

        # Envío a través de la API
        email = resend.Emails.send(params)
        
        print(f"[OK] Correo enviado exitosamente vía Resend. ID: {email.get('id')}")
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'success', 'id': email.get('id')})
        }

    except Exception as e:
        print(f"[ERROR] Error al enviar el correo a través de Resend: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }