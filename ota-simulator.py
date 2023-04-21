import sys
import bgapi
import getopt
import time

OTA_SERVICE_UUID = 0x1d14d6eefd634fa1bfa48f47b42119f0
OTA_CONTROL_UUID = 0xf7bf3564fb6d4e5388a45e37e0326063
ignored_events = ['bt_evt_connection_parameters',
                  'bt_evt_connection_phy_status',
                  'bt_evt_connection_remote_used_features']

xapi = 'sl_bt.xapi'
connector = None
baudrate = 115200
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
        print('         [ --ota ][ -a <bd-addr> ][ -l ]')
        quit()
        
opts,params = getopt.getopt(sys.argv[1:],'hvlt:u:x:b:a:n:d:',['ota'])
for opt,param in opts :
    if '-h' == opt :
        exit_help()
    if '-v' == opt :
        verbose += 1
    elif '-t' == opt :
        connector = bgapi.SocketConnector((param,4901))
    elif '-u' == opt :
        connector = bgapi.SerialConnector(param,bauderate=baudrate)
    elif '-x' == opt :
        xapi = param
    elif '-b' == opt :
        baudrate = int(param)
    elif '-l' == opt :
        list_mode = True
    elif '-d' == opt :
        duration = float(param)
    elif '-n' == opt :
        match_name = param
        match_service = None
        match_address = None
    elif '-a' == opt :
        match_address = param
        match_service = None
        match_name = None
    elif '--ota' == opt :
        ota_mode = True
    else :
        exit_help('Unrecognized option "%s"'%(opt))

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

def generate_gatt() :
    sid = dev.bt.gattdb.new_session().session
    ota_service = dev.bt.gattdb.add_service(sid,0,0,16,OTA_SERVICE_UUID.to_bytes(16,'little')).service
    dev.bt.gattdb.commit(sid)
    
def sl_bt_on_event(evt) :
    global app_rssi
    global timeout
    if 'bt_evt_system_boot' == evt :
        print('system-boot: BLE SDK %dv%dp%db%d'%(evt.major,evt.minor,evt.patch,evt.build))
        generate_gatt()
        adv_handle = dev.bt.advertiser.create_set().handle
        dev.bt.legacy_advertiser.generate_data(adv_handle,2)
        dev.bt.legacy_advertiser.start(adv_handle,2)
        setState('advertising')
    elif 'bt_evt_connection_opened' == evt :
        if 'connecting' != state :
            setState('confused')
        else :
            setState('connected')
    elif 'bt_evt_gatt_mtu_exchanged' == evt :
        setState('discovering-services')
        dev.bt.gatt.discover_primary_services(evt.connection)
    elif 'bt_evt_connection_closed' == evt :
        if 'expecting-close' :
            timeout = time.time() + duration
    else :
        unhandled = True
        for ignore in ignored_events :
            if ignore == evt :
                unhandled = False
        if unhandled :
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

