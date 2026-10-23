import Cocoa

final class ActionButton: NSButton {
  private var handler: (() -> Void)?
  init(_ title: String, handler: @escaping () -> Void) {
    super.init(frame: .zero)
    self.title = title
    self.handler = handler
    bezelStyle = .rounded
    setButtonType(.momentaryPushIn)
    controlSize = .large
    target = self
    action = #selector(fire)
  }
  required init?(coder: NSCoder) { fatalError("not used") }
  @objc private func fire() { handler?() }
}

final class Runner {
  private var process: Process?
  private var stdinHandle: FileHandle?
  private var buffer = Data()
  private let io = DispatchQueue(label: "sdimport.io")
  var onLine: ((String) -> Void)?
  var onExit: ((Int32) -> Void)?
  var isRunning: Bool { process?.isRunning ?? false }

  func start(python: String, script: String, args: [String]) throws {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: python)
    p.arguments = ["-I", "-B", "-u", script, "--gui"] + args
    var env = ProcessInfo.processInfo.environment
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    p.environment = env
    let out = Pipe()
    let inp = Pipe()
    p.standardOutput = out
    p.standardError = out
    p.standardInput = inp
    buffer = Data()
    out.fileHandleForReading.readabilityHandler = { [weak self] fh in
      let d = fh.availableData
      guard let self = self, !d.isEmpty else { return }
      self.io.async {
        self.buffer.append(d)
        self.drain(final: false)
      }
    }
    p.terminationHandler = { [weak self] proc in
      guard let self = self else { return }
      out.fileHandleForReading.readabilityHandler = nil
      let rest = out.fileHandleForReading.readDataToEndOfFile()
      self.io.async {
        self.buffer.append(rest)
        self.drain(final: true)
        DispatchQueue.main.async { self.onExit?(proc.terminationStatus) }
      }
    }
    try p.run()
    process = p
    stdinHandle = inp.fileHandleForWriting
  }

  private func drain(final: Bool) {
    while let nl = buffer.firstIndex(of: 0x0A) {
      let lineData = buffer.subdata(in: buffer.startIndex..<nl)
      buffer = buffer.subdata(in: (nl + 1)..<buffer.endIndex)
      emit(lineData)
    }
    if final && !buffer.isEmpty {
      emit(buffer)
      buffer = Data()
    }
  }

  private func emit(_ d: Data) {
    var line = String(decoding: d, as: UTF8.self)
    while line.hasSuffix("\r") { line.removeLast() }
    DispatchQueue.main.async { self.onLine?(line) }
  }

  func send(_ answer: String) {
    stdinHandle?.write(Data((answer + "\n").utf8))
  }
  func interrupt() { process?.interrupt() }
}

final class BackgroundView: NSView {
  override func draw(_ dirtyRect: NSRect) {
    NSColor.windowBackgroundColor.setFill()
    bounds.fill()
  }
}

final class CardView: NSView {
  override init(frame: NSRect) {
    super.init(frame: frame)
    wantsLayer = true
    layer?.cornerRadius = 16
    layer?.borderWidth = 1
    updateColors()
  }
  required init?(coder: NSCoder) { fatalError() }
  override func viewDidChangeEffectiveAppearance() { updateColors() }
  func updateColors() {
    effectiveAppearance.performAsCurrentDrawingAppearance {
      layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
      layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.35).cgColor
    }
  }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
  var window: NSWindow!
  let runner = Runner()
  let defaults = UserDefaults.standard
  var source: URL?
  var destination = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
    "Pictures/CardDock")
  let sourceLabel = NSTextField(labelWithString: "Choose a card or folder")
  let destinationLabel = NSTextField(labelWithString: "")
  let volumePicker = NSPopUpButton()
  var volumes: [URL] = []
  let layout = NSPopUpButton()
  let kind = NSPopUpButton()
  let shoot = NSTextField()
  let pathPreview = NSTextField(labelWithString: "")
  let deletion = NSButton(
    checkboxWithTitle: "Offer to delete verified originals after import", target: nil, action: nil)
  let includePrevious = NSButton(
    checkboxWithTitle: "Include previously imported files", target: nil, action: nil)
  let eject = NSButton(
    checkboxWithTitle: "Offer to eject the card when finished", target: nil, action: nil)
  let statusLabel = NSTextField(labelWithString: "Ready when you are.")
  let detailLabel = NSTextField(
    labelWithString: "Choose your source and destination. Your originals stay on the card.")
  let progress = NSProgressIndicator()
  let logView = NSTextView()
  let preview = NSButton(title: "Preview", target: nil, action: nil)
  let startButton = NSButton(title: "Import & Verify", target: nil, action: nil)
  let stopButton = NSButton(title: "Stop", target: nil, action: nil)
  var controls: [NSControl] = []
  var headline: String?
  var lastCode: Int32 = 0
  var wantsQuit = false
  var destinationNeedsSelection = false
  #if TESTING
    var testAnswers: [String] = []
  #endif

  func label(
    _ text: String, size: CGFloat = 13, weight: NSFont.Weight = .regular, secondary: Bool = false
  ) -> NSTextField {
    let v = NSTextField(labelWithString: text)
    v.font = .systemFont(ofSize: size, weight: weight)
    v.textColor = secondary ? .secondaryLabelColor : .labelColor
    return v
  }
  func stack(_ views: [NSView], vertical: Bool = false, spacing: CGFloat = 10) -> NSStackView {
    let s = NSStackView(views: views)
    s.orientation = vertical ? .vertical : .horizontal
    s.alignment = vertical ? .leading : .centerY
    s.spacing = spacing
    return s
  }
  func spacer() -> NSView {
    let v = NSView()
    v.setContentHuggingPriority(.defaultLow, for: .horizontal)
    return v
  }
  func card(_ content: NSView) -> CardView {
    let v = CardView()
    content.translatesAutoresizingMaskIntoConstraints = false
    v.addSubview(content)
    NSLayoutConstraint.activate([
      content.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 20),
      content.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -20),
      content.topAnchor.constraint(equalTo: v.topAnchor, constant: 18),
      content.bottomAnchor.constraint(equalTo: v.bottomAnchor, constant: -18),
    ])
    return v
  }
  func applicationDidFinishLaunching(_ note: Notification) {
    source = restore("source")
    if let saved = restore("destination") {
      destination = saved
    } else if defaults.data(forKey: "destinationBookmark") != nil {
      destinationNeedsSelection = true
      if let path = defaults.string(forKey: "destinationPath") {
        destination = URL(fileURLWithPath: path)
      }
    }
    buildMenu()
    buildWindow()
    runner.onLine = { [weak self] in self?.receive($0) }
    runner.onExit = { [weak self] in self?.finished($0) }
    refreshVolumes()
    NSWorkspace.shared.notificationCenter.addObserver(
      self, selector: #selector(refreshVolumes), name: NSWorkspace.didMountNotification, object: nil
    )
    NSWorkspace.shared.notificationCenter.addObserver(
      self, selector: #selector(refreshVolumes), name: NSWorkspace.didUnmountNotification,
      object: nil)
    updatePaths()
    #if TESTING
      if let config = ProcessInfo.processInfo.environment["CARDDOCK_TEST_CONFIG"],
        let data = config.data(using: .utf8),
        let o = try? JSONSerialization.jsonObject(with: data) as? [String: String]
      {
        if let s = o["source"] { source = URL(fileURLWithPath: s) }
        if let d = o["destination"] { destination = URL(fileURLWithPath: d) }
        destinationNeedsSelection = false
        testAnswers = (o["answers"] ?? "").components(separatedBy: ";")
        deletion.state = o["delete"] == "yes" ? .on : .off
        includePrevious.state = o["scope"] == "all" ? .on : .off
        if o["appearance"] == "dark" { window.appearance = NSAppearance(named: .darkAqua) }
        if o["width"] == "minimum" { window.setContentSize(NSSize(width: 820, height: 760)) }
        updatePaths()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
          self.snapshot("ready")
          if o["run"] == "import" {
            self.startButton.performClick(nil)
          } else if o["run"] == "preview" {
            self.preview.performClick(nil)
          } else {
            NSApp.terminate(nil)
          }
        }
      }
    #endif
  }
  func buildMenu() {
    let main = NSMenu()
    let item = NSMenuItem()
    let menu = NSMenu()
    item.submenu = menu
    menu.addItem(
      withTitle: "About CardDock",
      action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
    menu.addItem(.separator())
    menu.addItem(
      withTitle: "Quit CardDock", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"
    )
    main.addItem(item)
    let edit = NSMenuItem()
    let em = NSMenu(title: "Edit")
    edit.submenu = em
    for (t, a, k) in [
      ("Copy", #selector(NSText.copy(_:)), "c"), ("Paste", #selector(NSText.paste(_:)), "v"),
      ("Select All", #selector(NSText.selectAll(_:)), "a"),
    ] { em.addItem(withTitle: t, action: a, keyEquivalent: k) }
    main.addItem(edit)
    let help = NSMenuItem()
    let hm = NSMenu(title: "Help")
    help.submenu = hm
    hm.addItem(withTitle: "CardDock on GitHub", action: #selector(openHelp), keyEquivalent: "")
    main.addItem(help)
    NSApp.mainMenu = main
  }
  func buildWindow() {
    window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 900, height: 800),
      styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false
    )
    window.title = "CardDock"
    window.subtitle = "Verified photo imports"
    window.minSize = NSSize(width: 820, height: 760)
    window.center()
    window.setFrameAutosaveName("CardDockWindow")
    let root = BackgroundView()
    window.contentView = root
    let icon = NSImageView(
      image: NSImage(systemSymbolName: "sdcard.fill", accessibilityDescription: "SD card")!)
    icon.contentTintColor = .systemBlue
    icon.symbolConfiguration = .init(pointSize: 34, weight: .medium)
    icon.widthAnchor.constraint(equalToConstant: 52).isActive = true
    let heading = stack(
      [
        label("Bring your photos home.", size: 27, weight: .bold),
        label(
          "Original quality. Verified copies. Entirely on your Mac.", size: 13, secondary: true),
      ], vertical: true, spacing: 6)
    let badge = label("OFFLINE BY DESIGN", size: 10, weight: .semibold, secondary: true)
    let header = stack([icon, heading, spacer(), badge], spacing: 12)
    let chooseSource = ActionButton("Choose…") { [weak self] in self?.choose(isSource: true) }
    let chooseDest = ActionButton("Choose…") { [weak self] in self?.choose(isSource: false) }
    controls += [chooseSource, chooseDest, volumePicker]
    volumePicker.target = self
    volumePicker.action = #selector(selectVolume)
    volumePicker.widthAnchor.constraint(equalToConstant: 190).isActive = true
    for l in [sourceLabel, destinationLabel] {
      l.lineBreakMode = .byTruncatingMiddle
      l.font = .systemFont(ofSize: 13)
      l.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    }
    let sourceRow = stack([
      label("FROM", size: 10, weight: .bold, secondary: true), volumePicker, spacer(), chooseSource,
    ])
    let destRow = stack([
      label("TO", size: 10, weight: .bold, secondary: true), spacer(), chooseDest,
    ])
    let sourceCard = card(stack([sourceRow, sourceLabel], vertical: true, spacing: 10))
    let destCard = card(stack([destRow, destinationLabel], vertical: true, spacing: 10))
    let locations = stack([sourceCard, destCard], spacing: 14)
    sourceCard.widthAnchor.constraint(equalTo: destCard.widthAnchor).isActive = true
    sourceCard.heightAnchor.constraint(equalTo: destCard.heightAnchor).isActive = true
    layout.addItems(withTitles: ["Date · 2026-10-23", "Year / Month / Day"])
    layout.selectItem(at: defaults.integer(forKey: "layout"))
    layout.target = self
    layout.action = #selector(settingsChanged)
    kind.addItems(withTitles: ["Photos & videos", "Photos only", "Videos only"])
    kind.selectItem(at: defaults.integer(forKey: "kind"))
    kind.target = self
    kind.action = #selector(settingsChanged)
    shoot.placeholderString = "Shoot name (optional)"
    shoot.stringValue = defaults.string(forKey: "shoot") ?? ""
    shoot.target = self
    shoot.action = #selector(settingsChanged)
    shoot.widthAnchor.constraint(greaterThanOrEqualToConstant: 190).isActive = true
    NotificationCenter.default.addObserver(
      forName: NSControl.textDidChangeNotification, object: shoot, queue: .main
    ) { [weak self] _ in self?.settingsChanged() }
    let optionsRow = stack(
      [
        stack(
          [label("Organize into", size: 11, secondary: true), layout], vertical: true, spacing: 5),
        stack([label("Import", size: 11, secondary: true), kind], vertical: true, spacing: 5),
        stack(
          [label("Add a label", size: 11, secondary: true), shoot], vertical: true, spacing: 5),
      ], spacing: 20)
    pathPreview.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
    pathPreview.textColor = .secondaryLabelColor
    pathPreview.lineBreakMode = .byTruncatingMiddle
    let separator = NSBox()
    separator.boxType = .separator
    deletion.target = self
    deletion.action = #selector(settingsChanged)
    includePrevious.isEnabled = false
    // Destructive preferences deliberately reset on every launch.
    eject.state = defaults.bool(forKey: "eject") ? .on : .off
    eject.target = self
    eject.action = #selector(settingsChanged)
    let organize = card(
      stack(
        [optionsRow, pathPreview, separator, deletion, includePrevious, eject], vertical: true,
        spacing: 10))
    controls += [layout, kind, shoot, deletion, includePrevious, eject]
    let statusIcon = NSImageView(
      image: NSImage(
        systemSymbolName: "checkmark.shield", accessibilityDescription: "Checksum verification")!)
    statusIcon.contentTintColor = .systemBlue
    statusIcon.widthAnchor.constraint(equalToConstant: 26).isActive = true
    statusLabel.font = .systemFont(ofSize: 14, weight: .semibold)
    detailLabel.font = .systemFont(ofSize: 12)
    detailLabel.textColor = .secondaryLabelColor
    detailLabel.lineBreakMode = .byTruncatingTail
    progress.style = .bar
    progress.isIndeterminate = false
    progress.minValue = 0
    progress.maxValue = 100
    let status = stack(
      [stack([statusIcon, statusLabel, spacer()]), detailLabel, progress], vertical: true,
      spacing: 8)
    logView.isEditable = false
    logView.isRichText = false
    logView.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
    logView.textContainerInset = NSSize(width: 12, height: 10)
    logView.backgroundColor = .textBackgroundColor
    logView.isVerticallyResizable = true
    logView.autoresizingMask = [.width]
    logView.textContainer?.widthTracksTextView = true
    let scroll = NSScrollView()
    scroll.hasVerticalScroller = true
    scroll.documentView = logView
    scroll.wantsLayer = true
    scroll.layer?.cornerRadius = 10
    scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 100).isActive = true
    logView.string =
      "Your import activity will appear here.\n\nEvery copy is checked with SHA-256. Originals are never resized or re-encoded."
    let finder = ActionButton("Show Destination") { [weak self] in
      if let d = self?.destination { NSWorkspace.shared.open(d) }
    }
    preview.bezelStyle = .rounded
    preview.target = self
    preview.action = #selector(previewImport)
    startButton.bezelStyle = .rounded
    startButton.controlSize = .large
    startButton.keyEquivalent = "\r"
    startButton.target = self
    startButton.action = #selector(startImport)
    stopButton.bezelStyle = .rounded
    stopButton.target = self
    stopButton.action = #selector(stopImport)
    stopButton.isHidden = true
    let footer = stack([finder, spacer(), stopButton, preview, startButton])
    let content = stack(
      [header, locations, organize, status, scroll, footer], vertical: true, spacing: 18)
    content.translatesAutoresizingMaskIntoConstraints = false
    root.addSubview(content)
    NSLayoutConstraint.activate([
      content.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 26),
      content.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -26),
      content.topAnchor.constraint(equalTo: root.topAnchor, constant: 24),
      content.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -22),
    ])
    for v in [header, locations, organize, status, scroll, footer] {
      v.widthAnchor.constraint(equalTo: content.widthAnchor).isActive = true
    }
    for v in [sourceRow, destRow] {
      v.widthAnchor.constraint(equalTo: sourceCard.widthAnchor, constant: -40).isActive = true
    }
    for v in [optionsRow, pathPreview, separator] {
      v.widthAnchor.constraint(equalTo: organize.widthAnchor, constant: -40).isActive = true
    }
    progress.widthAnchor.constraint(equalTo: status.widthAnchor).isActive = true
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
  }
  func remember(_ url: URL, key: String) {
    defaults.set(url.path, forKey: key + "Path")
    if let data = try? url.bookmarkData(
      options: [], includingResourceValuesForKeys: [.volumeUUIDStringKey], relativeTo: nil)
    {
      defaults.set(data, forKey: key + "Bookmark")
    }
    let uuid = try? url.resourceValues(forKeys: [.volumeUUIDStringKey]).volumeUUIDString
    defaults.set(uuid, forKey: key + "Volume")
  }
  func restore(_ key: String) -> URL? {
    guard let data = defaults.data(forKey: key + "Bookmark") else { return nil }
    var stale = false
    guard
      let u = try? URL(
        resolvingBookmarkData: data, options: [.withoutUI, .withoutMounting], relativeTo: nil,
        bookmarkDataIsStale: &stale), FileManager.default.fileExists(atPath: u.path)
    else { return nil }
    if let saved = defaults.string(forKey: key + "Volume"),
      let actual = try? u.resourceValues(forKeys: [.volumeUUIDStringKey]).volumeUUIDString,
      saved != actual
    {
      return nil
    }
    if stale { remember(u, key: key) }
    return u
  }
  func choose(isSource: Bool) {
    let p = NSOpenPanel()
    p.canChooseDirectories = true
    p.canChooseFiles = false
    p.allowsMultipleSelection = false
    p.canCreateDirectories = !isSource
    p.prompt = isSource ? "Choose Source" : "Choose Destination"
    p.message =
      isSource
      ? "Select a card or a folder containing photos and videos."
      : "Choose where verified originals will be saved."
    p.beginSheetModal(for: window) { [weak self] response in
      guard let self = self, response == .OK, let url = p.url else { return }
      if isSource {
        self.source = url
      } else {
        self.destination = url
        self.destinationNeedsSelection = false
      }
      self.remember(url, key: isSource ? "source" : "destination")
      self.updatePaths()
    }
  }
  @objc func refreshVolumes() {
    guard !runner.isRunning else { return }
    volumes =
      (FileManager.default.mountedVolumeURLs(
        includingResourceValuesForKeys: [.volumeIsRemovableKey, .volumeIsEjectableKey],
        options: [.skipHiddenVolumes]) ?? []).filter { u in
        let v = try? u.resourceValues(forKeys: [.volumeIsRemovableKey, .volumeIsEjectableKey])
        return v?.volumeIsRemovable == true || v?.volumeIsEjectable == true
      }
    volumePicker.removeAllItems()
    volumePicker.addItem(withTitle: "Connected drives…")
    for u in volumes { volumePicker.addItem(withTitle: u.lastPathComponent) }
  }
  @objc func selectVolume() {
    let i = volumePicker.indexOfSelectedItem - 1
    if volumes.indices.contains(i) {
      source = volumes[i]
      remember(volumes[i], key: "source")
      updatePaths()
    }
  }
  @objc func settingsChanged() {
    defaults.set(layout.indexOfSelectedItem, forKey: "layout")
    defaults.set(kind.indexOfSelectedItem, forKey: "kind")
    defaults.set(shoot.stringValue, forKey: "shoot")
    defaults.set(eject.state == .on, forKey: "eject")
    includePrevious.isEnabled = deletion.state == .on
    updatePaths()
  }
  func updatePaths() {
    sourceLabel.stringValue = source?.path ?? "Choose a card or folder"
    sourceLabel.toolTip = source?.path
    destinationLabel.stringValue =
      destinationNeedsSelection
      ? "Reconnect your drive and choose its folder again" : destination.path
    destinationLabel.toolTip = destination.path
    let date = DateFormatter()
    date.dateFormat = layout.indexOfSelectedItem == 1 ? "yyyy/MM/dd" : "yyyy-MM-dd"
    pathPreview.stringValue =
      "Example: " + destination.lastPathComponent + "/" + date.string(from: Date())
      + (shoot.stringValue.isEmpty ? "" : " " + shoot.stringValue) + "/DSC_0001.JPG"
    startButton.isEnabled = source != nil && !runner.isRunning
    preview.isEnabled = source != nil && !runner.isRunning
  }
  @objc func previewImport() { begin(previewOnly: true) }
  @objc func startImport() { begin(previewOnly: false) }
  func begin(previewOnly: Bool) {
    guard !runner.isRunning, let source = source else { return }
    guard !destinationNeedsSelection else {
      alert(
        "Your saved destination is unavailable. Reconnect the drive and choose its folder again.")
      return
    }
    guard let script = Bundle.main.path(forResource: "sd_import", ofType: "py"),
      let resources = Bundle.main.resourceURL
    else {
      alert("The app is incomplete. Download a fresh copy from GitHub.")
      return
    }
    let python = resources.appendingPathComponent("python/bin/python3").path
    guard FileManager.default.isExecutableFile(atPath: python) else {
      alert("The bundled runtime is missing. Download a fresh copy from GitHub.")
      return
    }
    // If a remembered volume was replaced, require explicit selection again.
    for (key, url) in [("source", source), ("destination", destination)] {
      if let saved = defaults.string(forKey: key + "Volume"),
        let actual = try? url.resourceValues(forKeys: [.volumeUUIDStringKey]).volumeUUIDString,
        saved != actual
      {
        alert("The \(key) drive changed. Choose it again before importing.")
        return
      }
    }
    var args = [
      "--source", source.path, "--dest", destination.path, "--layout",
      layout.indexOfSelectedItem == 1 ? "nested" : "daily", "--kind",
      ["all", "photos", "videos"][max(0, kind.indexOfSelectedItem)], "--shoot", shoot.stringValue,
    ]
    if previewOnly {
      args.append("--dry-run")
    } else {
      if deletion.state == .on {
        args += ["--ask-delete", "--scope", includePrevious.state == .on ? "all" : "run"]
      }
      if eject.state == .on { args.append("--eject") }
    }
    headline = nil
    logView.string = ""
    statusLabel.stringValue = previewOnly ? "Previewing your import…" : "Preparing your import…"
    detailLabel.stringValue = "Reading originals and checking existing copies."
    progress.doubleValue = 0
    do {
      try runner.start(python: python, script: script, args: args)
      busy(true)
    } catch {
      alert(error.localizedDescription)
      busy(false)
    }
  }
  func busy(_ running: Bool) {
    for c in controls { c.isEnabled = !running }
    includePrevious.isEnabled = !running && deletion.state == .on
    startButton.isEnabled = !running && source != nil
    preview.isEnabled = startButton.isEnabled
    stopButton.isHidden = !running
  }
  @objc func stopImport() {
    statusLabel.stringValue = "Stopping safely…"
    runner.interrupt()
  }
  func receive(_ line: String) {
    guard line.hasPrefix("##"), let space = line.firstIndex(of: " "),
      let data = String(line[line.index(after: space)...]).data(using: .utf8),
      let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else {
      logView.textStorage?.append(
        NSAttributedString(
          string: line + "\n",
          attributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: NSColor.labelColor,
          ]))
      logView.scrollToEndOfDocument(nil)
      return
    }
    switch String(line.dropFirst(2).prefix(while: { $0 != " " })) {
    case "STATUS": statusLabel.stringValue = o["text"] as? String ?? ""
    case "PROGRESS":
      progress.doubleValue = o["pct"] as? Double ?? 0
      detailLabel.stringValue = o["text"] as? String ?? ""
    case "DONE": headline = o["headline"] as? String
    case "PROMPT": prompt(o)
    default: break
    }
  }
  func prompt(_ o: [String: Any]) {
    let a = NSAlert()
    let k = o["kind"] as? String ?? ""
    let n = o["files"] as? Int ?? 0
    var answer = ""
    if k == "delete" {
      a.messageText = "Keep originals on the card?"
      a.informativeText =
        "\(n) files have verified destination copies. Keeping originals is the default."
      a.addButton(withTitle: "Keep Originals")
      a.addButton(withTitle: "Review Deletion…")
      answer = "1"
    } else if k == "confirm" {
      a.alertStyle = .critical
      a.messageText = "Permanently delete \(n) originals?"
      a.informativeText =
        "Both copies will be checked again before each removal. Camera-protected files will be kept. Deletion cannot be undone."
      a.addButton(withTitle: "Cancel")
      let b = a.addButton(withTitle: "Delete Verified Originals")
      b.hasDestructiveAction = true
      answer = "DELETE"
    } else if k == "eject" {
      a.messageText = "Eject the card?"
      a.addButton(withTitle: "Leave Connected")
      a.addButton(withTitle: "Eject")
      answer = "y"
    } else {
      runner.send("")
      return
    }
    a.beginSheetModal(for: window) { [weak self] response in
      self?.runner.send(response == .alertSecondButtonReturn ? answer : "")
    }
    #if TESTING
      if ProcessInfo.processInfo.environment["CARDDOCK_TEST_CONFIG"] != nil {
        let selected = testAnswers.isEmpty ? "" : testAnswers.removeFirst()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
          self.snapshot("prompt-" + k)
          a.buttons[selected == answer ? 1 : 0].performClick(nil)
        }
      }
    #endif
  }
  func finished(_ rc: Int32) {
    lastCode = rc
    busy(false)
    statusLabel.stringValue =
      rc == 0 ? "All done." : rc == 130 ? "Import stopped." : "Some items need attention."
    detailLabel.stringValue = headline ?? "See the activity log for details."
    detailLabel.toolTip = detailLabel.stringValue
    if rc == 0 { progress.doubleValue = 100 }
    if wantsQuit { NSApp.reply(toApplicationShouldTerminate: true) }
    #if TESTING
      if ProcessInfo.processInfo.environment["CARDDOCK_TEST_CONFIG"] != nil {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
          self.snapshot("finished")
          print("TEST_EXIT \(rc) \(self.detailLabel.stringValue)")
          NSApp.terminate(nil)
        }
      }
    #endif
  }
  func alert(_ text: String) {
    let a = NSAlert()
    a.messageText = text
    a.addButton(withTitle: "OK")
    a.beginSheetModal(for: window)
  }
  @objc func openHelp() {
    NSWorkspace.shared.open(URL(string: "https://github.com/edcadet10/carddock")!)
  }
  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
  func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    guard runner.isRunning else { return .terminateNow }
    let a = NSAlert()
    a.messageText = "Stop this import and quit?"
    a.informativeText =
      "Completed copies are kept. Any originals already deleted cannot be restored by stopping."
    a.addButton(withTitle: "Keep Importing")
    a.addButton(withTitle: "Stop & Quit")
    if a.runModal() == .alertSecondButtonReturn {
      wantsQuit = true
      runner.interrupt()
      return .terminateLater
    }
    return .terminateCancel
  }
  #if TESTING
    func snapshot(_ name: String) {
      guard let folder = ProcessInfo.processInfo.environment["CARDDOCK_SCREENSHOTS"],
        let view = window.contentView,
        let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds)
      else { return }
      view.cacheDisplay(in: view.bounds, to: rep)
      try? rep.representation(using: .png, properties: [:])?.write(
        to: URL(fileURLWithPath: folder).appendingPathComponent(name + ".png"))
    }
  #endif
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
