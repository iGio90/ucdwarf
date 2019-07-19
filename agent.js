function Emulator() {
    this.clean = function () {
        loggedSend('emulator:::clean')
    };

    this.setup = function (tid, arch, mode) {
        if (typeof tid !== 'number') {
            tid = Process.getCurrentThreadId();
        }
        var msg = 'emulator:::setup:::' + tid;
        if (isDefined(arch) && isDefined(mode)) {
            msg += ':::' + arch + ':::' + mode;
        }
        loggedSend(msg)
    };

    this.start = function (until) {
        loggedSend('emulator:::start:::' + until)
    };

    this.step = function () {
        loggedSend('emulator:::step:::1')
    };

    this.stepFunction = function () {
        loggedSend('emulator:::step:::2')
    };

    this.stepJump = function () {
        loggedSend('emulator:::step:::3')
    };

    this.stop = function () {
        loggedSend('emulator:::stop')
    };
}

global.emulator = new Emulator();
