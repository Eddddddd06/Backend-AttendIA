import resend
import json
import os

resend.api_key = os.environ.get('RESEND_API_KEY')

def lambda_handler(event, context):
    try:
        print(f"[INFO] Evento crudo recibido desde el disparador: {json.dumps(event)}")
        
        if "Records" in event:
            print("[INFO] Detectado evento originado en AWS SNS. Desempaquetando payload...")
            sns_message = event["Records"][0]["Sns"]["Message"]
            event = json.loads(sns_message) 
            print(f"[INFO] Payload de ticket extraído con éxito: {json.dumps(event)}")

        to_email = event.get('to_email')
        subject = event.get('subject', 'Actualización de tu Ticket')
        body_content = event.get('body_content', 'Tu ticket ha sido actualizado.')

        if not to_email:
            print("[ERROR] No se proporcionó el correo de destino ('to_email')")
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'Falta el correo de destino.'})
            }

       
        params = {
            "from": "AttendIA <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "text": body_content,
        }

        print(f"[INFO] Enviando correo a {to_email} a través de la API de Resend...")
        
        email = resend.Emails.send(params)
        email_id = email.get('id')
        
        print(f"[OK] Correo enviado exitosamente vía Resend. ID asignado: {email_id}")
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'success', 'id': email_id})
        }

    except Exception as e:
        print(f"[ERROR] Excepción atrapada en enviar_email: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
