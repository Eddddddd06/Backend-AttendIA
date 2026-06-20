import boto3
import json
import os

# Inicializamos el cliente de AWS SES en la región actual
ses_client = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# El correo que registraste y verificaste en AWS SES
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'tu_correo_verificado@gmail.com')

def lambda_handler(event, context):
    """
    Lambda Asíncrono para enviar notificaciones por correo electrónico usando AWS SES.
    Recibe el payload del Lambda de resolver tickets.
    """
    try:
        print(f"[INFO] Evento recibido para enviar correo: {json.dumps(event)}")
        
        # Extraer los datos del payload enviado asíncronamente
        to_email = event.get('to_email')
        subject = event.get('subject', 'Actualización de tu Ticket')
        body_content = event.get('body_content', 'Tu ticket ha sido actualizado.')

        if not to_email:
            print("[ERROR] No se proporcionó el correo de destino ('to_email')")
            return {'statusCode': 400, 'body': 'Falta el correo de destino.'}

        # Estructurar el envío con AWS SES
        response = ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={
                'ToAddresses': [to_email]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_content,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )

        print(f"[OK] Correo enviado exitosamente a {to_email}. MessageId: {response['MessageId']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'success', 'message': f'Correo enviado a {to_email}'})
        }

    except Exception as e:
        print(f"[ERROR] Error al enviar el correo a través de SES: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }