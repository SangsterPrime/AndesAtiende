from app.funciones import minimiza_pii, RESPUESTAS

def test_minimiza_contacto():
    s=minimiza_pii('Mi correo es contacto@example.cl y quiero ayuda')
    assert 'contacto@example.cl' not in s
    assert '[CORREO]' in s

def test_cancelacion_no_automatica():
    assert 'no cancela' in RESPUESTAS['anulacion'].lower()
