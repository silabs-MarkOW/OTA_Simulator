import sys
import bgapi
import getopt
import time

ota_characteristics = {
    0xF7BF3564FB6D4E5388A45E37E0326063:{
        'name':'OTA Control',
        'properties':0x08
    },
    0x984227F334FC4045A5D02C581F81A153:{
        'name':'OTA Data',
        'properties':0x0c
    },
    0x4F4A23688CCA451EBFFFCF0E2EE23E9F:{
        'name':'AppLoader Version',
        'properties':0x02
    },
    0x4CC07BCF08684B329DADBA4CC41E5316:{
        'name':'OTA Version',
        'properties':0x02
    },
    0x25F05C0AE91746E9B2A5AA2BE1245AFE:{
        'name':'Gecko Bootloader Version',
        'properties':0x02
    },
    0xD77CC114AC149F2BFA9CD96AC7A92F8:{
        'name':'Application Version',
        'properties':0x02
    }
}
            
OTA_SERVICE_UUID = 0x1d14d6eefd634fa1bfa48f47b42119f0

xapi = 'sl_bt.xapi'
connector = None
baudrate = 115200

config = {'name':'OTA Simulator','reset-on-close':False, 'characteristics':{} }
issues = {'num_buffers_discarded':0, 'num_buffer_allocation_failures':0}
transfer = { 'bytes':0, 'packets':0 }
connection = {'mtu':27}
identity = 'application'

target = {'address':None}
state = 'start'
duration = 10
timeout = None
app_rssi = None
verbose = 0
ota_mode = False
match_service = 0x1509
match_name = None
list_mode = False
devices = {}

def exit_help(error=None) :
    if None != error :
        print('Error: %s'%(error))
        print('Usage %s [ -h ][ -v ][ -t <ip-address> ][ -u <uart> ][ -b baudrate ]')
        print('         [ -x <api-xml> ][ -d <duration> ][ -n <complete-local-name> ]')
        print('         [ --no-app ][ -a <bd-addr> ][ -l ]')
        quit()
        
opts,params = getopt.getopt(sys.argv[1:],'hvlt:u:x:b:a:n:d:',['no-app'])
for opt,param in opts :
    if '-h' == opt :
        exit_help()
    if '-v' == opt :
        verbose += 1
    elif '-t' == opt :
        connector = bgapi.SocketConnector((param,4901))
    elif '-u' == opt :
        connector = bgapi.SerialConnector(param,baudrate=baudrate)
    elif '-x' == opt :
        xapi = param
    elif '-b' == opt :
        if None != connector :
            exit_help('Because I am lazy, -b must be placed before -u')
        baudrate = int(param)
    elif '-l' == opt :
        list_mode = True
    elif '-d' == opt :
        duration = float(param)
    elif '-n' == opt :
        config['name'] = param
    elif '-a' == opt :
        match_address = param
        match_service = None
        match_name = None
    elif '--no-app' == opt :
        identity = 'apploader'
    else :
        exit_help('Unrecognized option "%s"'%(opt))

print(config)

if None == connector :
    exit_help('Either -t or -u is required')

try :
    dev = bgapi.BGLib(connection=connector,apis=xapi)
except FileNotFoundError :
    exit_help('xml file defining API, %s, not found. See -x option')

def setState(new_state) :
    global state
    print('set_state: %s -> %s'%(state,new_state))
    state = new_state

def addRemoveCharacteristic(uuid,characteristic,service) :
    #print('addRemoveCharacteristic(characteristic:%s,service:%s)'%(characteristic.__str__(),service.__str__()))
    if None == service :
        if 'OTA Control' == characteristic['name'] :
            return True,None
        if 'apploader' == identity :
            return True,None
        return False,None
    try :
        handle = dev.bt.gatt_server.find_attribute(0,characteristic.to_bytes(16,'little'))
        if 'OTA Control' == characteristic['name'] or 'apploader' == identity :
            return False,None
        return False,handle
    except bgapi.bglib.CommandFailedError:
        if 'OTA Control' == characteristic['name'] or 'apploader' == identity :
            return True,None
        return False,None

def complex_generate_gatt() :
    global connection
    global identity
    global config
    bytesOtaService = OTA_SERVICE_UUID.to_bytes(16,'little')
    ota_service = None
    try :
        ota_service = dev.bt.gatt_server.find_attribute(0,bytesOtaService)
        print(ota_service)
    except bgapi.bglib.CommandFailedError:
        print('FAILURE',(ota_service))
    characteristicsToAdd = []
    characteristicsToRemove = []
    for c in ota_characteristics :
        cd = ota_characteristics[c]
        add,remove = addRemoveCharacteristic(c,cd,ota_service)
        if add : characteristicsToAdd.append(c)
        if None != remove : characteristicsToRemove.append(remove)
    sid = dev.bt.gattdb.new_session().session
    print('sid:',sid,'bytesUUID:',bytesOtaService)
    ota_service = dev.bt.gattdb.add_service(sid,0,0,bytesOtaService).service
    print('ota_service:',ota_service)
    for c in characteristicsToRemove :
        dev.bt.gattdb.remove_service(sid,c)
    for c in characteristicsToAdd :
        cd = ota_characteristics[c]
        bytesUUID = c.to_bytes(16,'little')
        properties = cd['properties']
        print('adding UUID  0x%x, properties: 0x%x'%(c,properties))
        dev.bt.gattdb.add_uuid128_characteristic(sid,ota_service,properties,0,0,bytesUUID, 3,0,b'')
    dev.bt.gattdb.start_service(sid,ota_service)
    dev.bt.gattdb.commit(sid)
    for c in characteristicsToAdd :        
        handle = dev.bt.gatt_server.find_attribute(0,c.to_bytes(16,'little')).attribute
        config['characteristics'][handle] = c
    print(config)
    if(0):
        handle = 0
        while True :
            try :
                resp = dev.bt.gatt_server.read_attribute_type(handle)
                print('handle:%d, UUID:0x%x'%(handle,int.from_bytes(resp.type,'little')))
            except bgapi.bglib.CommandFailedError:
                print('handle:%d, result: 0x%04x'%(handle,resp.result))
            handle += 1

def generate_gatt() :
    sid = dev.bt.gattdb.new_session().session
    ota_service = dev.bt.gattdb.add_service(sid,0,0,OTA_SERVICE_UUID.to_bytes(16,'little')).service
    added_characteristics = []
    for c in ota_characteristics :
        cd = ota_characteristics[c]
        if 'OTA Control' == cd['name'] or 'apploader' == identity :
            bytesUUID = c.to_bytes(16,'little')
            properties = cd['properties']
            print('adding UUID  0x%x, properties: 0x%x'%(c,properties))
            dev.bt.gattdb.add_uuid128_characteristic(sid,ota_service,properties,0,0,bytesUUID, 3,0,b'')
            added_characteristics.append(c)
    dev.bt.gattdb.start_service(sid,ota_service)
    dev.bt.gattdb.commit(sid)
    for c in added_characteristics :
        handle = dev.bt.gatt_server.find_attribute(0,c.to_bytes(16,'little')).attribute
        config['characteristics'][handle] = c
    
def start_advertising() :
    global config
    handle = dev.bt.advertiser.create_set().handle
    if 'application' == identity :
        flags = b'\x02\x01\x06'
        encodedName = config['name'].encode()
        mainPayload = flags + (len(encodedName)+1).to_bytes(1,'little') + b'\x09' + encodedName
    elif 'apploader' == identity :
        flags = b'\x02\x01\x06'
        encodedName = 'OTA'.encode()
        mainPayload = flags + (len(encodedName)+1).to_bytes(1,'little') + b'\x09' + encodedName
    else :
        print('start-advertising called with identity "%s"'%(identity))
        return setState('confused')
    if len(mainPayload) > 31 :
         raise RuntimeError('mainPayload too long')
    dev.bt.legacy_advertiser.set_data(handle,0,mainPayload)
    dev.bt.legacy_advertiser.start(handle,2)
    setState('advertising')

def on_write_request(characteristic,offset,value) :
    global connection
    global identity
    global transfer
    uuid = config['characteristics'].get(characteristic)
    if None == uuid :
        print('Unhandled write to characteristic handle %d'%(characteristic))
    else :
        name = ota_characteristics[uuid]['name']
        if 'OTA Control' == name :
            if 'apploader-transfer' == state :
                print(', time: %.1fs'%(time.time() - transfer['start']))
            print('%s written to %s'%(value.__str__(),name))
            if b'\x00' == value and 'application' == identity :
                identity = 'application-to-apploader'
                dev.bt.connection.close(connection['handle'])
                setState('application-closing')
                return 0
            elif b'\x00' == value and 'apploader' == identity :
                setState('apploader-transfer')
                transfer['packets'] = 0
                transfer['bytes'] = 0
                transfer['histo'] = {}
                transfer['start'] = time.time()
                return 0
            elif b'\x03' == value and 'apploader-transfer' == state :
                setState('apploader-done')
                return 0
            elif b'\x04' == value and 'apploader' == identity :
                setState('apploader-done-close')
                return 0
            else :
                setState('confused')
                return 0x84
        elif 'OTA Data' == name :
            if 'apploader-transfer' == state :
                length = len(value)
                count = transfer['histo'].get(length)
                if None == count : count = 0
                transfer['histo'][length] = count + 1
                transfer['packets'] += 1
                transfer['bytes'] += length
                dt = time.time() - transfer['start']
                nbytes = transfer['bytes']
                print('\r%7.2fk bytes %5.1f kbit/s'%(nbytes/1024,8*nbytes/1024/dt),end='',flush=True)
                return 0
    return 0x85

def sl_bt_on_event(evt) :
    global app_rssi
    global timeout
    global identity
    if 'bt_evt_system_boot' == evt :
        if 'reset' == state :
            print('system-boot: BLE SDK %dv%dp%db%d'%(evt.major,evt.minor,evt.patch,evt.build))
            address = dev.bt.system.get_identity_address().address
            print('OTA Simulator address: %s'%(address))
        elif len(state) < 6 or 'reset-' != state[:6] :
            return setState('confused')
        if 'reset-to-application' == state :
            identity = 'application'
        if 'reset-to-apploader' == state :
            identity = 'apploader'
        generate_gatt()
        start_advertising()
            
    elif 'bt_evt_connection_opened' == evt :
        connection['handle'] = evt.connection
        print('connection from %s'%(evt.address))
        if 'advertising' != state :
            setState('confused')
        else :
            setState('connected')
    elif 'bt_evt_gatt_mtu_exchanged' == evt :
        connection['mtu'] = evt.mtu
    elif 'bt_evt_connection_closed' == evt :
        print(issues)
        if 'closing' :
            if 'application-to-apploader' == identity :
                setState('reset-to-apploader')
                dev.bt.system.reset(0)
            elif 'apploader' == identity :
                setState('reset-to-application')
                dev.bt.system.reset(0)
            else :
                print('connection close in identity "%s"'%(identity))
                return setState('confused')
        else :
                print('connection close in state "%s"'%(state))
                return setState('confused')
    elif 'bt_evt_gatt_server_user_write_request' == evt :
        rc = on_write_request(evt.characteristic,evt.offset,evt.value)
        if 0x12 == evt.att_opcode :
            dev.bt.gatt_server.send_user_write_response(evt.connection,evt.characteristic,rc)
        if 'application-to-apploader' == evt :
            dev.bt.connection.close(evt.connection)
        if 'apploader-done' == state or 'apploader-done-close' == state :
            print(transfer)
    elif 'bt_evt_gatt_server_user_read_request' == evt :
        uuid = config['characteristics'].get(evt.characteristic)
        if None == uuid :
            print('Characteristic %d read')
            rc = None
        else :
            name = ota_characteristics[uuid]['name']
            print('%s read'%(name))
            if 'AppLoader Version' == name :
                rc = b'\x04\x00\x02\x00\x02\x00\x85\x01'
            elif 'OTA Version' == name :
                rc = b'\x03'
            elif 'Gecko Bootloader Version' == name :
                rc = b'\x02\x00\x02\x02'
            elif 'Application Version' == name :
                rc = b'\x01\x00\x00\x00'
            else :
                print('Unhandled UUID 0x%X'%(uuid))
        if None == rc :
            dev.bt.gatt_server.send_user_read_response(evt.connection,evt.characteristic,0x80,b'')
        else :
            dev.bt.gatt_server.send_user_read_response(evt.connection,evt.characteristic,0x00,rc)
    elif 'bt_evt_system_resource_exhausted' == evt :
        issues['num_buffers_discarded'] += evt.num_buffers_discarded
        issues['num_buffer_allocation_failures'] += evt.num_buffer_allocation_failures
    else :
        print('Unhandled event: %s'%(evt.__str__()))
    return state != 'confused'

dev.open()
dev.bt.system.reset(0)
setState('reset')

# keep scanning for events
while 'done' != state :
    try:
        # print('Starting point...')
        evt = dev.get_events(max_events=1)
        if evt:
            if not sl_bt_on_event(evt[0]) :
                break
    except(KeyboardInterrupt, SystemExit) as e:
        if dev.is_open():
            dev.close()
            print('Exiting...')
            sys.exit(1)

if dev.is_open():
    dev.close()
